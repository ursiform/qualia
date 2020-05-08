import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="qualia",
    version="0.1.0",
    author="Afshin T. Darian",
    author_email="qualia@darian.af",
    description="qualia",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ursiform/qualia",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
