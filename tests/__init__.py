# Tests run against the English source strings; tests that check the Turkish
# translation select it explicitly. Subprocesses inherit TARTIM_LANG.
import os

os.environ["TARTIM_LANG"] = "en"

from tartim import i18n  # noqa: E402

i18n.setup("en")
