"""
Setup script for Dspx-Monitor
Cryogenic Dilution Refrigerator Monitoring Dashboard
"""

from setuptools import setup, find_packages

setup(
    name="dspx-monitor",
    version="1.0.0",
    description="Cryogenic Dilution Refrigerator Monitoring Dashboard",
    author="MIT-Despereaux",
    python_requires=">=3.8,<3.9",
    install_requires=[
        "streamlit==1.22.0",
        # "pandas>=1.3.0,<1.5.0",  # Pinned to avoid pyarrow dependency issues on 32-bit systems
        "requests>=2.25.0",
        "plotly>=5.0.0",
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
