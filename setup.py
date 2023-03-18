from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in espresso_sync/__init__.py
from espresso_sync import __version__ as version

setup(
	name="espresso_sync",
	version=version,
	description="A General Purpose 2-Way Sync Engine for Importing and Exporting data between Frappe sites and external APIs.",
	author="Avunu LLC",
	author_email="mail@avu.nu",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
