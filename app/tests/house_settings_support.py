"""A household's Home Assistant settings as the tests give them, since none ship: the values one household wrote, and the
shipped general rules with them applied."""

from ashley.home_assistant import irreversible
from ashley.home_assistant.house_values import HouseValues
from ashley.tools import home_assistant_config
from ashley.tools.house_act import Rules

LISTS = ("todo.inbox", "todo.groceries", "todo.weekly_shopping")
VALUES = HouseValues(household_reads={"todo.get_items": LISTS},
                     service_reads=("script.drive_time", "weather.get_forecasts"),
                     reads=("script.find_person", "script.find_recipe", "script.recipe_details",
                            "script.drive_time"))


def house_rules(values: HouseValues = VALUES) -> Rules:
    """The shipped `excluded` and `irreversible`, with `values` applied as a turn applies them."""
    return Rules(home_assistant_config.load().excluded, (), irreversible.load()).for_household(values)
