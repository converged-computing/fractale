import os

from setuptools import find_packages, setup


def get_lookup():
    lookup = dict()
    version_file = os.path.join("fractale", "version.py")
    with open(version_file) as filey:
        exec(filey.read(), lookup)
    return lookup


def get_reqs(lookup=None, key="INSTALL_REQUIRES"):
    if lookup is None:
        lookup = get_lookup()

    install_requires = []
    for module in lookup[key]:
        module_name = module[0]
        module_meta = module[1]
        if "exact_version" in module_meta:
            dependency = "%s==%s" % (module_name, module_meta["exact_version"])
        elif "min_version" in module_meta:
            if module_meta["min_version"] is None:
                dependency = module_name
            else:
                dependency = "%s>=%s" % (module_name, module_meta["min_version"])
        elif "max_version" in module_meta:
            if module_meta["max_version"] is None:
                dependency = module_name
            else:
                dependency = "%s<=%s" % (module_name, module_meta["max_version"])

        install_requires.append(dependency)
    return install_requires


# Make sure everything is relative to setup.py
install_path = os.path.dirname(os.path.abspath(__file__))
os.chdir(install_path)

# Get version information from the lookup
lookup = get_lookup()
VERSION = lookup["__version__"]
NAME = lookup["NAME"]
AUTHOR = lookup["AUTHOR"]
AUTHOR_EMAIL = lookup["AUTHOR_EMAIL"]
PACKAGE_URL = lookup["PACKAGE_URL"]
KEYWORDS = lookup["KEYWORDS"]
DESCRIPTION = lookup["DESCRIPTION"]
LICENSE = lookup["LICENSE"]

# Try to read description, otherwise fallback to short description
try:
    with open("README.md") as filey:
        LONG_DESCRIPTION = filey.read()
except Exception:
    LONG_DESCRIPTION = DESCRIPTION

################################################################################
# MAIN #########################################################################
################################################################################

if __name__ == "__main__":
    INSTALL_REQUIRES = get_reqs(lookup)
    TESTS_REQUIRES = get_reqs(lookup, "TESTS_REQUIRES")
    INSTALL_REQUIRES_ALL = get_reqs(lookup, "INSTALL_REQUIRES_ALL")
    GOOGLE_REQUIRES = get_reqs(lookup, "GOOGLE_REQUIRES")
    OPENAI_REQUIRES = get_reqs(lookup, "OPENAI_REQUIRES")
    AUTOGEN_REQUIRES = get_reqs(lookup, "AUTOGEN_REQUIRES")
    LANGCHAIN_REQUIRES = get_reqs(lookup, "AUTOGEN_REQUIRES")

    setup(
        name=NAME,
        version=VERSION,
        author=AUTHOR,
        author_email=AUTHOR_EMAIL,
        maintainer=AUTHOR,
        packages=find_packages(),
        include_package_data=True,
        zip_safe=False,
        url=PACKAGE_URL,
        license=LICENSE,
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        long_description_content_type="text/markdown",
        keywords=KEYWORDS,
        setup_requires=["pytest-runner"],
        install_requires=INSTALL_REQUIRES,
        tests_require=TESTS_REQUIRES,
        extras_require={
            "all": [INSTALL_REQUIRES_ALL],
            "google": [GOOGLE_REQUIRES],
            "openai": [OPENAI_REQUIRES],
            "autogen": [AUTOGEN_REQUIRES],
            "langchain": [LANGCHAIN_REQUIRES],
        },
        classifiers=[
            "Intended Audience :: Science/Research",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            "Programming Language :: C",
            "Programming Language :: Python",
            "Topic :: Software Development",
            "Topic :: Scientific/Engineering",
            "Operating System :: Unix",
            "Programming Language :: Python :: 3.11",
        ],
        entry_points={"console_scripts": ["fractale=fractale.cli:run_fractale"]},
    )
