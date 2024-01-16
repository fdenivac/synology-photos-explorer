from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="synology-photos-explorer",
    description="Explorer for Synology Photos",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/fdenivac/synology-photos-explorer",
    version="1.0.0",
    author="fedor denivac",
    author_email="fdenivac@gmail.com",
    license="GNU GPLv3",
    keywords="explorer synology photo pyqt qt",
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.10",
        "Topic :: Multimedia :: Graphics",
    ],
    python_requires=">=3.10",
    package_dir={"synology-photos-explorer": "synology-photos-explorer"},
    packages=["synology-photos-explorer"],
    scripts=[
        "SynoPhotosExplorer.py",
    ],
    install_requires=[
        "python-dotenv",
        "PyQt6",
        "synology-api @ git+https://github.com/fdenivac/synology-api",
    ],
)
