import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name='VoiPy',
    version='1.0.7',
    description='Voip package',
    author='Seyed Saeid Dehghani',
    author_email="s.saeid.dehghani@gmail.com",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/SeyedSaeidDehghani/VoiPy",
    install_requires=["scapy>=2.4.5",
                      "requests>=2.26.0",
                      "setuptools>=42",
                      "wheel"],
    license="GNU GPLv3",
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: Microsoft :: Windows :: Windows 10",
    ],
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    python_requires="==3.9.1",
)
