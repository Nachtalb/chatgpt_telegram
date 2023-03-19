import asyncio
import inspect
from typing import AsyncIterable, AsyncIterator, TypeVar


def get_arg_value(arg_name, func, args, kwargs):
    if arg_name in kwargs:
        return kwargs[arg_name]

    # Get the argument index from the function signature
    signature = inspect.signature(func)
    index = list(signature.parameters.keys()).index(arg_name)

    if index < len(args):
        return args[index]
    else:
        return None  # The argument was not provided


T = TypeVar("T")


async def async_throttled_iterator(async_iterator: AsyncIterable[T], delay: float | int) -> AsyncIterator[T | None]:
    last_item: T | None = None
    item_available = asyncio.Event()
    iterator_exhausted = asyncio.Event()

    async def consume_items():
        nonlocal last_item
        async for item in async_iterator:
            last_item = item
            item_available.set()
        iterator_exhausted.set()

    async def produce_items():
        while not iterator_exhausted.is_set() or item_available.is_set():
            await item_available.wait()
            item_available.clear()
            yield last_item
            if not iterator_exhausted.is_set():
                await asyncio.sleep(delay)

    async def cleanup(task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    consume_task = asyncio.create_task(consume_items())
    try:
        async for item in produce_items():
            yield item
    finally:
        consume_task.cancel()
        await cleanup(consume_task)


def stabelise_string(string: str, replace_brackets: bool = True) -> str:
    for char in ["(", ")", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"] + (["[", "]"] if replace_brackets else []):
        string = string.replace(char, rf"\{char}")
    return string
