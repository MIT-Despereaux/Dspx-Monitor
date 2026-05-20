"""
Setup script for Dspx-Monitor
Cryogenic Dilution Refrigerator Monitoring Dashboard
"""

from setuptools import setup

setup(
    name="dspx-monitor",
    version="2.1.0",
    description="Cryogenic Dilution Refrigerator Monitoring Dashboard",
    author="MIT-Despereaux",
    python_requires=">=3.11",
    py_modules=["app", "core", "scheduler"],
    packages=[],
    install_requires=[
        "streamlit",
        "pandas",
        "requests",
        "plotly",
        "protobuf",
        "slack_sdk",
        "schedule",
    ],
    extras_require={
        "dev": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "dspx-monitor=app:main",
        ],
    },
)
