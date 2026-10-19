"""Composable async stream steps: `a >> b >> c`. Core ported from fact-assessor.

A step turns an async stream of items into an async stream of items. Per-item steps (`Map`, `FlatMap`,
`Filter`) run items concurrently and pass each result on the moment it is ready, so a chain streams.
Closing a stream (`Take(n)` reaching n, a consumer breaking out) cancels the unfinished work upstream.

In a chain a plain function is a `Map` and a `Predicate` is a `Filter`. Building a chain runs nothing:
`await chain.run(x)` returns a list, `chain.stream(x)` yields items as they arrive.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import Any

_ITEM, _ERROR, _END = object(), object(), object()


class Step:
    """Base: implement `__call__(items) -> AsyncIterator`. Compose with `>>`."""

    def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        raise NotImplementedError

    def __rshift__(self, other: Any) -> Chain:
        return Chain(self, as_step(other))

    def __rrshift__(self, other: Any) -> Chain:  # `fn >> step`
        return Chain(as_step(other), self)

    def stream(self, item: Any) -> AsyncIterator[Any]:
        """Feed one item, yield outputs as they arrive."""
        return self(once(item))

    async def run(self, item: Any) -> list[Any]:
        """Feed one item, return every output."""
        return await collect(self(once(item)))

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class Chain(Step):
    def __init__(self, *steps: Step) -> None:
        self.steps: list[Step] = [s for st in steps for s in (st.steps if isinstance(st, Chain) else [st])]

    def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        for step in self.steps:
            items = step(items)
        return items

    def __repr__(self) -> str:
        return " >> ".join(map(repr, self.steps))


class FlatMap(Step):
    """Each item -> 0..n items. `fn(item)` returns an async iterable."""

    def __init__(self, fn: Callable[[Any], AsyncIterable[Any]], concurrency: int | None = None) -> None:
        self.fn = fn
        self.concurrency = concurrency

    def __repr__(self) -> str:
        return f"{type(self).__name__}({_name(self.fn)})"

    def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        return _concurrently(items, self.fn, self.concurrency)


class Map(Step):
    """Each item -> one item, or dropped if `fn` returns None. Sync keeps order; async runs concurrently."""

    def __init__(self, fn: Callable[[Any], Any], concurrency: int | None = None) -> None:
        self.fn = fn
        self.concurrency = concurrency

    def __repr__(self) -> str:
        return f"{type(self).__name__}({_name(self.fn)})"

    def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        if not _is_async(self.fn):
            return _in_order(items, lambda item: [] if (r := self.fn(item)) is None else [r])

        async def one(item: Any) -> AsyncIterator[Any]:
            if (result := await self.fn(item)) is not None:
                yield result

        return _concurrently(items, one, self.concurrency)


class Filter(Step):
    """Keep items where `pred(item)` is true. Sync keeps order; async runs concurrently."""

    def __init__(self, pred: Callable[[Any], Any], concurrency: int | None = None) -> None:
        self.pred = pred
        self.concurrency = concurrency

    def __repr__(self) -> str:
        return f"{type(self).__name__}({_name(self.pred)})"

    def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        if not _is_async(self.pred):
            return _in_order(items, lambda item: [item] if self.pred(item) else [])

        async def one(item: Any) -> AsyncIterator[Any]:
            if await self.pred(item):
                yield item

        return _concurrently(items, one, self.concurrency)


class Take(Step):
    """The first n items, passed on as they arrive; then closes the stream upstream."""

    def __init__(self, n: int) -> None:
        self.n = n

    async def __call__(self, items: AsyncIterator[Any]) -> AsyncIterator[Any]:
        try:
            count = 0
            if self.n <= 0:
                return
            async for item in items:
                yield item
                count += 1
                if count >= self.n:
                    return
        finally:
            await _aclose(items)

    def __repr__(self) -> str:
        return f"Take({self.n})"


class Predicate:
    """A sync condition that combines with `&`, `|`, `~`. In a chain it becomes a `Filter`."""

    def __init__(self, fn: Callable[[Any], bool]) -> None:
        self.fn = fn

    def __call__(self, item: Any) -> bool:
        return bool(self.fn(item))

    def __and__(self, other: Callable[[Any], bool]) -> Predicate:
        return Predicate(lambda x: self(x) and other(x))

    def __or__(self, other: Callable[[Any], bool]) -> Predicate:
        return Predicate(lambda x: self(x) or other(x))

    def __invert__(self) -> Predicate:
        return Predicate(lambda x: not self(x))

    def __rshift__(self, other: Any) -> Chain:
        return Chain(Filter(self), as_step(other))


def as_step(x: Any) -> Step:
    """What `>>` accepts: a Step as is, a Predicate as a Filter, any other callable as a Map."""
    if isinstance(x, Step):
        return x
    if isinstance(x, Predicate):
        return Filter(x)
    if callable(x):
        return Map(x)
    raise TypeError(f"cannot chain {x!r}: not a Step, Predicate or callable")


async def once(item: Any) -> AsyncIterator[Any]:
    """A one-item stream: the usual source for a chain."""
    yield item


async def collect(stream: AsyncIterator[Any]) -> list[Any]:
    """Drain a stream into a list."""
    return [item async for item in stream]


# ---- internals -------------------------------------------------------------------------------------------


async def _concurrently(
    items: AsyncIterator[Any], run: Callable[[Any], AsyncIterable[Any]], limit: int | None
) -> AsyncIterator[Any]:
    """Run `run(item)` for every item, at most `limit` at once; yield outputs as they appear.
    An item only starts once it has a slot, so a slow stage also slows how fast upstream is read."""
    queue: asyncio.Queue[tuple[object, Any]] = asyncio.Queue()
    slots = asyncio.Semaphore(limit) if limit else None
    tasks: set[asyncio.Task[None]] = set()

    async def worker(item: Any) -> None:
        try:
            async for out in run(item):
                await queue.put((_ITEM, out))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  surfaced to the consumer
            await queue.put((_ERROR, exc))
        finally:
            if slots:
                slots.release()

    async def feeder() -> None:
        try:
            async for item in items:
                if slots:
                    await slots.acquire()
                task = asyncio.create_task(worker(item))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            while tasks:
                await asyncio.gather(*list(tasks), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await queue.put((_ERROR, exc))
            return
        finally:
            await _aclose(items)
        await queue.put((_END, None))

    feed = asyncio.create_task(feeder())
    try:
        while True:
            kind, value = await queue.get()
            if kind is _END:
                return
            if kind is _ERROR:
                raise value
            yield value
    finally:
        feed.cancel()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(feed, *tasks, return_exceptions=True)


async def _in_order(items: AsyncIterator[Any], fn: Callable[[Any], list[Any]]) -> AsyncIterator[Any]:
    try:
        async for item in items:
            for out in fn(item):
                yield out
    finally:
        await _aclose(items)


def _name(fn: Any) -> str:
    return getattr(fn, "__qualname__", None) or type(fn).__name__


def _is_async(fn: Any) -> bool:
    call = getattr(type(fn), "__call__", None)  # noqa: B004  async callable objects, not callable()
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(call)


async def _aclose(items: Any) -> None:
    if (close := getattr(items, "aclose", None)) is not None:
        await close()
