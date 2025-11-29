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
    py_modules=["app"],  # Single module, not a package
    packages=[],  # Explicitly empty to prevent auto-discovery of data/assets folders
    python_requires=">=3.8,<3.9",
    install_requires=[
        "streamlit==0.62",  # Pinned to avoid pyarrow dependency
        "click<8.0.0",  # Required for streamlit 0.62 compatibility
        "numpy<1.24.0",  # Required for np.bool compatibility with older streamlit
        "pandas>=1.3.0,<1.5.0",  # Pinned to avoid pyarrow dependency issues on 32-bit systems
        "requests>=2.25.0",
        "plotly>=5.0.0",
        "protobuf<=3.20",
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
