"""
GetRich 量化交易系统安装配置文件
"""

from setuptools import setup, find_packages

# 读取 README 作为长描述
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# 读取依赖
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="getrich",
    version="0.1.0",
    author="GetRich Team",
    author_email="",
    description="量化交易系统 - 模块化设计的期货/期权交易平台",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    packages=find_packages(exclude=["tests", "reference", "*.pyc", "__pycache__"]),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Financial and Insurance Industry",
        "Topic :: Office/Business :: Financial :: Investment",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    # extras_require={
    #     "dev": [
    #         "pytest>=7.0.0",
    #         "pytest-cov>=4.0.0",
    #         "black>=22.0.0",
    #         "flake8>=5.0.0",
    #         "pylint>=2.15.0",
    #     ],
    # },
    # entry_points={
    #     "console_scripts": [
    #         # 可以在这里添加命令行工具
    #         # "getrich-data=Data.clickhouse.service:main",
    #     ],
    # },
    include_package_data=True,
    package_data={
        "Data": ["clickhouse/config/*.yml", "clickhouse/table/*.sql"],
    },
    zip_safe=False,
)
