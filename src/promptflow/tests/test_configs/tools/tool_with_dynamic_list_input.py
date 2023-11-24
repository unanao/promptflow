from promptflow._core.tool import tool
from promptflow.entities import InputSetting, DynamicList
from typing import List, Union, Dict


def my_list_func(prefix: str = "", size: int = 10, **kwargs) -> List[Dict[str, Union[str, int, float, list, Dict]]]:
    """This is a dummy function to generate a list of items.

    :param prefix: prefix to add to each item.
    :param size: number of items to generate.
    :param kwargs: other parameters.
    :return: a list of items. Each item is a dict with the following keys:
        - value: for backend use. Required.
        - display_value: for UI display. Optional.
        - hyperlink: external link. Optional.
        - description: information icon tip. Optional.
    """
    import random

    words = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape", "honeydew", "kiwi", "lemon"]
    result = []
    for i in range(size):
        random_word = f"{random.choice(words)}{i}"
        cur_item = {
            "value": random_word,
            "display_value": f"{prefix}_{random_word}",
            "hyperlink": f'https://www.google.com/search?q={random_word}',
            "description": f"this is {i} item",
        }
        result.append(cur_item)

    return result


dynamic_list_setting = DynamicList(function=my_list_func, input_mapping={"prefix": "input_prefix"})
input_settings = {
    "input_text": InputSetting(
        dynamic_list=dynamic_list_setting,
        allow_manual_entry=True,
        is_multi_select=True
    )
}


@tool(
    name="My Tool with Dynamic List Input",
    description="This is my tool with dynamic list input",
    input_settings=input_settings
)
def my_tool(input_text: list, input_prefix: str) -> str:
    return f"Hello {input_prefix} {','.join(input_text)}"
