################
iris-cicd-tools
################

A Python library providing unified abstractions for CI/CD tools like `Dagger <https://dagger.io/>`_ and `Invoke <https://www.pyinvoke.org/>`_.

=========
Overview
=========

``iris-cicd-tools`` is designed to bridge the gap between different CI/CD frameworks by providing a consistent, environment-agnostic configuration context. Instead of duplicating pipeline logic across Dagger and Invoke (or other tools), you define your CI/CD logic once and reuse it everywhere.

Currently, the library specializes in **Sphinx documentation builds** with support for:

- Multi-branch documentation deployment
- Multi-language documentation builds
- Consistent context across GitHub Actions, GitLab CI, and local environments
- Automatic index page generation with language/branch redirects

=========
Features
=========

- **CIDocContext**: A unified configuration class that detects the CI environment and provides consistent access to:
  
  - Branch name and commit hash
  - Project metadata (name, repository URL)
  - Documentation base URLs for GitHub Pages or GitLab Pages
  - Git user information for CI commits
  - Installation and build instructions for Sphinx environments

- **sphinx_conf_extractor**: A utility to safely extract the ``html_context`` from your Sphinx configuration, enabling dynamic and data-driven documentation builds.

- **Environment detection**: Automatically identifies GitHub Actions, GitLab CI, and local environments.

=============
Installation
=============

Using ``uv`` (recommended):

.. code-block:: bash

    uv pip install iris-cicd-tools

Using ``pip``:

.. code-block:: bash

    pip install iris-cicd-tools

Requirements
-------------

- Python 3.11+
- typeguard>=4.5.1

======
Usage
======

Basic Example with Dagger
--------------------------

.. code-block:: python

    from iris_cicd_tools import CIDocContext
    
    # Initialize context from your project root
    context = CIDocContext(root_dir="/path/to/project")
    
    # Get environment info
    print(f"Branch: {context.branch_name}")
    print(f"Commit: {context.commit_hash}")
    print(f"Is GitHub Actions: {context.is_github}")
    
    # Get installation instructions for container
    install_cmds = context.get_install_instructions()
    
    # Get build instructions (requires html_context from Sphinx)
    build_info = context.get_build_instructions(html_context={
        "language_per_branch": {
            "main": ["en"],
            "dev": ["en", "fr"]
        },
        "default_language": "en",
        "default_branch": "main"
    })

Basic Example with Invoke
--------------------------

.. code-block:: python

    from iris_cicd_tools import CIDocContext
    from invoke import task
    
    @task
    def build_docs(c):
        context = CIDocContext(root_dir=".")
        build_info = context.get_build_instructions(html_context=...)
        
        for cmd in build_info["commands"]:
            c.run(" ".join(cmd))

======================
Environment Variables
======================

The library detects your CI environment using standard environment variables:

**GitHub Actions**:

- ``GITHUB_ACTIONS`` = ``"true"``
- ``GITHUB_REPOSITORY`` (e.g., ``owner/repo``)
- ``GITHUB_SHA`` (commit hash)
- ``GITHUB_REF_NAME`` (branch name)

**GitLab CI**:

- ``GITLAB_CI`` = ``"true"``
- ``CI_PROJECT_NAME``
- ``CI_COMMIT_SHA``
- ``CI_COMMIT_REF_NAME``
- ``CI_REPOSITORY_URL``

**Local**: Falls back to local ``git`` commands if neither is set.

==================
Project Structure
==================

.. code-block:: text

    src/iris_cicd_tools/
    ├── __init__.py               # Package entry point
    ├── doc.py                    # CIDocContext class (main API)
    ├── env_context.py            # Environment variable definitions
    ├── sphinx_conf_extractor.py  # Sphinx config extraction utility
    └── index.template.html       # Template for redirect pages

============
Development
============

Requirements
-------------

- Python 3.11+
- ``uv`` for package management

Setup
------

.. code-block:: bash

    git clone <repository>
    cd iris_cicd_tools
    uv sync

Type Checking
--------------

This package is fully typed using PEP 561 annotations and ``typeguard`` runtime checks.

.. code-block:: bash

    # Type checking with mypy or pyright
    mypy src/

========
License
========

See LICENSE file for details.

=============
Contributing
=============

Contributions are welcome! Please ensure:

- All code is type-checked
- Tests pass (when tests are added)
- Docstrings follow standard conventions
