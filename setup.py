from setuptools import find_packages, setup

setup(
    name="aa-recruitment",
    version="0.1.0",
    description="Recruitment and Application Management Plugin for Alliance Auth",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Maddog Broekman",
    author_email="maddogbroekman@gmail.com",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "aa_recruitment": [
            "locale/*/*/*",
            "templates/*/*",
        ],
    },
    install_requires=[
        "allianceauth>=3.6.0",
        "requests>=2.28.0",
    ],
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Django",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP",
    ],
    python_requires=">=3.10",
)
