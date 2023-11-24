# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import os
import re
from pathlib import Path
from typing import Any, Match, cast

from setuptools import find_packages, setup

PACKAGE_NAME = "promptflow"
PACKAGE_FOLDER_PATH = Path(__file__).parent / "promptflow"

with open(os.path.join(PACKAGE_FOLDER_PATH, "_version.py"), encoding="utf-8") as f:
    version = cast(Match[Any], re.search(r'^VERSION\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE)).group(1)

with open("README.md", encoding="utf-8") as f:
    readme = f.read()
with open("CHANGELOG.md", encoding="utf-8") as f:
    changelog = f.read()

REQUIRES = [
    "psutil",  # get process information when bulk run
    "httpx>=0.25.1",  # used to send http requests asynchronously
    "openai>=0.27.8,<0.28.0",  # promptflow.core.api_injector
    "flask>=2.2.3,<3.0.0",  # Serving endpoint requirements
    "flask-restx>=1.2.0,<1.3.0",  # Serving endpoint requirements
    "sqlalchemy>=1.4.48,<3.0.0",  # sqlite requirements
    # note that pandas 1.5.3 is the only version to test in ci before promptflow 0.1.0b7 is released
    # and pandas 2.x.x will be the only version to test in ci after that.
    "pandas>=1.5.3,<3.0.0",  # load data requirements
    "python-dotenv>=1.0.0,<2.0.0",  # control plane sdk requirements, to load .env file
    "keyring>=24.2.0,<25.0.0",  # control plane sdk requirements, to access system keyring service
    "pydash>=6.0.0,<8.0.0",  # control plane sdk requirements, to support parameter overrides in schema.
    # vulnerability: https://github.com/advisories/GHSA-5cpq-8wj7-hf2v
    "cryptography>=41.0.3,<42.0.0",  # control plane sdk requirements to support connection encryption
    "colorama>=0.4.6,<0.5.0",  # producing colored terminal text for testing chat flow
    "tabulate>=0.9.0,<1.0.0",  # control plane sdk requirements, to print table in console
    "filelock>=3.4.0,<4.0.0",  # control plane sdk requirements, to lock for multiprocessing
    # We need to pin the version due to the issue: https://github.com/hwchase17/langchain/issues/5113
    "marshmallow>=3.5,<4.0.0",
    "pyyaml>=5.1.0,<7.0.0",
    "gitpython>=3.1.24,<4.0.0",  # used git info to generate flow id
    "tiktoken>=0.4.0",
    "strictyaml>=1.5.0,<2.0.0",  # used to identify exact location of validation error
    "waitress>=2.1.2,<3.0.0",  # used to serve local service
    "opencensus-ext-azure<2.0.0",  # configure opencensus to send telemetry to azure monitor
    "ruamel.yaml>=0.17.35,<0.18.0",  # used to generate connection templates with preserved comments
    "pyarrow>=9.0.0,<15.0.0",  # used to read parquet file with pandas.read_parquet
    "pillow>=10.1.0,<11.0.0",  # used to generate icon data URI for package tool
    "filetype>=1.2.0",  # used to detect the mime type for mulitmedia input
]

setup(
    name=PACKAGE_NAME,
    version=version,
    description="Prompt flow Python SDK - build high-quality LLM apps",
    long_description_content_type="text/markdown",
    long_description=readme + "\n\n" + changelog,
    license="MIT License",
    author="Microsoft Corporation",
    author_email="aml-pt-eng@microsoft.com",
    url="https://github.com/microsoft/promptflow",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires="<4.0,>=3.8",
    install_requires=REQUIRES,
    extras_require={
        "azure": [
            "azure-core>=1.26.4,<2.0.0",
            "azure-storage-blob>=12.13.0,<13.0.0",
            "azure-identity>=1.12.0,<2.0.0",
            "azure-ai-ml>=1.11.0,<2.0.0",
            "pyjwt>=2.4.0,<3.0.0",  # requirement of control plane SDK
        ],
        "executable": ["pyinstaller>=5.13.2", "streamlit>=1.26.0", "streamlit-quill<0.1.0", "bs4"],
    },
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "pf = promptflow._cli._pf.entry:main",
            "pfazure = promptflow._cli._pf_azure.entry:main",
            "pfs = promptflow._sdk._service.entry:main",
        ],
    },
    include_package_data=True,
    project_urls={
        "Bug Reports": "https://github.com/microsoft/promptflow/issues",
        "Source": "https://github.com/microsoft/promptflow",
    },
)
