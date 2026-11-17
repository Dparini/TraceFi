import os

from hypothesis import settings

settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, database=None)
settings.register_profile(
    "stress", max_examples=2000, deadline=None, derandomize=True, database=None
)
settings.register_profile(
    "mutation", max_examples=40, deadline=None, derandomize=True, database=None
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
