import asyncio
import time

import pytest

from abyss import Filter, FlatMap, Map, Predicate, Step, Take, collect, once


async def numbers(n):
    for i in range(n):
        yield i


async def test_plain_functions_chain_as_map_and_keep_order():
    chain = Map(lambda x: x + 1) >> (lambda x: x * 10)
    assert await collect(chain(numbers(4))) == [10, 20, 30, 40]


async def test_map_returning_none_drops_item():
    chain = Map(lambda x: x if x % 2 else None)
    assert await collect(chain(numbers(6))) == [1, 3, 5]


async def test_predicate_combinators_filter():
    even = Predicate(lambda x: x % 2 == 0)
    big = Predicate(lambda x: x > 2)
    assert await collect(Filter(even & big)(numbers(8))) == [4, 6]
    assert await collect(Filter(~even)(numbers(5))) == [1, 3]
    assert await collect((Map(lambda x: x) >> (even | big))(numbers(5))) == [0, 2, 3, 4]


async def test_flatmap_one_to_many():
    async def twice(x):
        yield x
        yield x

    assert sorted(await collect(FlatMap(twice)(numbers(3)))) == [0, 0, 1, 1, 2, 2]


async def test_async_map_runs_concurrently():
    async def slow(x):
        await asyncio.sleep(0.1)
        return x

    t0 = time.perf_counter()
    out = await collect(Map(slow)(numbers(10)))
    assert sorted(out) == list(range(10))
    assert time.perf_counter() - t0 < 0.5  # 10 x 0.1s in parallel, not 1s


async def test_concurrency_limit_is_respected():
    running = peak = 0

    async def tracked(x):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return x

    await collect(Map(tracked, concurrency=3)(numbers(12)))
    assert peak == 3


async def test_take_stops_and_cancels_upstream():
    finished = []

    async def slow(x):
        await asyncio.sleep(0.05 * (x + 1))
        finished.append(x)
        return x

    out = await collect((Map(slow) >> Take(2))(numbers(10)))
    assert out == [0, 1]
    await asyncio.sleep(0.3)
    assert len(finished) < 10  # the rest were cancelled, not left running


async def test_run_and_stream_feed_one_item():
    chain = Map(lambda s: s.upper()) >> (lambda s: s + "!")
    assert await chain.run("hi") == ["HI!"]
    assert [x async for x in chain.stream("yo")] == ["YO!"]
    assert await collect(chain(once("a"))) == ["A!"]


async def test_chains_nest_and_flatten():
    a = Map(lambda x: x + 1) >> Map(lambda x: x * 2)
    b = a >> Take(2)
    assert len(b.steps) == 3
    assert await collect(b(numbers(5))) == [2, 4]


async def test_errors_propagate():
    async def boom(x):
        raise ValueError("bad")

    with pytest.raises(ValueError):
        await collect(Map(boom)(numbers(3)))


async def test_custom_step_subclass():
    class Double(Step):
        async def __call__(self, items):
            async for x in items:
                yield x
                yield x

    assert await (Double() >> Take(3)).run(7) == [7, 7]


def test_chaining_non_callable_raises():
    with pytest.raises(TypeError):
        Take(1) >> 42


def test_reprs_are_readable():
    def double(x):
        return x * 2

    class Mine(Step):
        pass

    assert repr(Map(double) >> Take(2)) == "Map(test_reprs_are_readable.<locals>.double) >> Take(2)"
    assert repr(Mine()) == "Mine()"


def test_version_matches_package_metadata():
    from importlib.metadata import version

    import abyss

    assert abyss.__version__ == version("llm-abyss") == "0.1.0"
