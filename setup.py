"""
Setup script for Dspx-Monitor
Cryogenic Dilution Refrigerator Monitoring Dashboard
"""

from setuptools import setup, find_packages

setup(
    name="dspx-monitor",
    version="2.0.0",
    description="Cryogenic Dilution Refrigerator Monitoring Dashboard",
    author="MIT-Despereaux",
    python_requires=">=3.13",
    py_modules=["app"],
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
