import os
import time
import subprocess
import shlex
import inspect
from pathlib import Path
from urllib.parse import urlparse

import asyncio

from typing import Callable, Awaitable
from typeguard import typechecked

from .env_context import ENVIRONMENT_VARIABLES

def located_commands(commands: list[str], workdir : str, shell="sh" ) -> list[list[str]]:
    """
    Rewrite a list of shell commands to be executed in a single shell session with a specified working directory
    and using shell, "-c" to ensure that environment variables and state persist across commands.
    """
    return [[shell, "-c", f"cd {workdir} && " + cmd] for cmd in commands]

class CIDocContext:
    """
    A unified configuration context shared by both Dagger and Invoke.
    Calculates branch names, commit hashes, and URLs consistently.
    """
    def __init__(self, 
                 root_dir: str | Path,
                 run_local_git_commands: Callable[[list[str]], str | Awaitable[str]] | None = None):
        self.root_dir = Path(root_dir).resolve()
        self.sphinx_relative_dir = Path("doc") / "sphinx"
        self.sphinx_dir = self.root_dir / self.sphinx_relative_dir
        self.gitlab_public_dir = Path("/") / "public"
        
        # Locate the directory where this python package resides to find the template
        self.package_dir = Path(__file__).parent.resolve()

        self.is_github = os.environ.get("GITHUB_ACTIONS") == "true"
        self.is_gitlab = os.environ.get("GITLAB_CI") == "true"
        self.is_local = not (self.is_github or self.is_gitlab)
        self.run_local_git_commands = run_local_git_commands if run_local_git_commands else self._run_local_git

        self.branch_name = None
        self.commit_hash = None
        self.remote = None
        self.project_name = None
        self.repo_url = None
        self.doc_base_url = None
        self.auth_repo_url = None
        self.action_email = None
        self.action_name = None
        self.output_dir : str | None = None

    async def setup(self):
        """Initialize the context by gathering all necessary information from the environment and git."""
        self.branch_name = await self.get_branch_name()
        self.commit_hash = await self.get_commit_hash()
        self.remote = await self.get_remote()
        self.project_name = self.get_project_name()
        self.repo_url = self._get_repo_url()
        self.doc_base_url = self._get_doc_base_url()
        self.auth_repo_url = self._get_auth_repo_url()
        self.action_email, self.action_name = self._get_git_action_user_info()
        return self
    
    async def _exec_git(self, cmd: list[str]) -> str:
        """
        Le cœur de la magie : s'adapte à la signature de run_local_git_commands.
        """
        result = self.run_local_git_commands(cmd)
        
        # Si c'est une coroutine (ex: Dagger), on l'attend.
        if inspect.isawaitable(result):
            return await result
            
        # Si c'est une string directe (ex: Invoke), on la retourne.
        return result

    @typechecked
    def build_env_workdir_relative(self) -> Path:
        """
        Returns the relative path to the Sphinx directory from the root of the repository.
        This is used to set the working directory for build commands in both Dagger and Invoke.
        """
        return self.sphinx_relative_dir

    @typechecked
    def get_context_html_cmd(self, sphinx_path: str ) -> list[str]:
        """
        Provides the command that calls the iris_cicd_tools.sphinx_conf_extractor module
        to extract necessary context from the Sphinx configuration.
        This MUST be executed inside the build environment (Container or Local Venv).
        """
        return ["sh", "-c", f". {sphinx_path}/.venv/bin/activate && python3 -m iris_cicd_tools.sphinx_conf_extractor --config-path {sphinx_path}/source/conf.py"]

    @typechecked
    def get_install_instructions(self) -> list[list[str]]:
        """
        Generates the installation instructions for the Sphinx build environment.
        This can be used by both Dagger and Invoke to set up the environment consistently.
        Code must be run from the root of the repository to ensure correct paths.
        """
        return [
            # System Dependencies
            ["apt-get", "update", "-qq"],
            ["apt-get", "install", "-y", "-qq", "libcairo2-dev", "libcairo2","pkg-config", "build-essential", "git", "make", "cmake", "python3-dev", "python3-venv", "python3-sphinx"],
            
            # Python Dependencies
            ["python3", "-m", "venv", ".venv"],
            ["sh", "-c", ". .venv/bin/activate && pip install -r requirements.txt"],

            # Install iris_cicd_tools into the build container so that the 
            # sphinx_conf_extractor module can be used to extract configuration from conf.py
            ["sh", "-c", ". .venv/bin/activate && pip install git+https://github.com/ICube-Robotics/iris_cicd_tools.git"]
        ]

    @typechecked
    def get_email_cmd() -> list[str]:
        """
        Returns the command to get the git user email for commits in CI environments.
        This is used in the deployment phase to ensure that commits are attributed correctly.
        """
        return ["git", "config", "--get", "user.email"]
            
    
    @typechecked
    def get_name_cmd() -> list[str]:
        """
        Returns the command to get the git user name for commits in CI environments.
        This is used in the deployment phase to ensure that commits are attributed correctly.
        """
        return ["git", "config", "--get", "user.name"]

    @typechecked
    def _get_git_action_user_info(self) -> tuple[str, str]:
        # TODO(@yguel) investigate if it is not more valuable to provide commit user info instead of CI bot?
        """
        Determines the user email and name to use for git commits in CI environments.
        For GitHub Actions, it uses 'action@github.com' and 'GitHub Action'.
        For GitLab CI, it uses 'gitlab-ci-token' and 'GitLab CI'.
        For local environments, it defaults to the current git config user or a generic fallback.
        """
        if self.is_github:
            return "action@github.com", "GitHub Action"
        elif self.is_gitlab:
            return "gitlab-ci-token", "GitLab CI"
        else:
            # Try to get the local git user config, but provide a fallback if not set
            email = "CIbot@local"
            name = "CI Bot"
            return email, name


    @typechecked
    def _get_auth_repo_url(self) -> str | None:
        if self.repo_url:
            parsed = urlparse(self.repo_url)
            clean_host = parsed.hostname
            clean_path = parsed.path

            if self.is_github:
                return f"https://oauth2:${{SECRET_TOKEN}}@{clean_host}{clean_path}"
            else:
                # Assume gitlab
                return f"https://gitlab-ci-token:${{SECRET_TOKEN}}@{clean_host}{clean_path}"
        return None

    @typechecked
    def get_build_instructions(self, html_context: dict) -> dict:
        """
        Parses the Sphinx html_context and generates the necessary shell commands 
        and copy operations required to build the documentation.
        This allows both Dagger and Invoke to use the exact same build logic.
        Supposes that the working directory is set to the sphinx directory.
        """
        commands = []

        # Activate the virtual environment for subsequent commands
        commands.append(["sh", "-c", ". .venv/bin/activate"])
        
        # 1. Get Languages
        try:
            langs = html_context.get('language_per_branch', {}).get(self.branch_name)
        except Exception as e:
            print(f"WARNING: Failed to extract 'language_per_branch' from html_context: {e}")
            langs = None
        if not langs:
            lang_groups = html_context.get('languages', [])
            langs = [x[0] for x in lang_groups if len(x) > 0 and isinstance(x[0], str)]
        
        # If there is no language specified for the current branch, we default to English:
        if not langs:
            print(f"No languages specified in general or for branch '{self.branch_name}'. Defaulting to English.")
            langs = ["en"]
        
        # 2. Translation pass
        if len(langs) > 1:
            # In case of multiple languages, call gettext to extract translatable strings and 
            # compile translations before building HTML for each language
            commands.append(["make", "gettext"])
            commands.append(["sphinx-build", "-b", "gettext", "source", "build/gettext"])

        # 3. Build HTML for each language
        for lang in langs:
            output_path = f"{self.branch_name}/{lang}"
            # Create a separate output directory for each language 
            # to avoid conflicts and ensure correct caching
            cmd = ["sh", "-c", f"mkdir -p build/html/{output_path}"]
            commands.append(cmd)
            
            # Handle different logo per language if specified in the configuration
            # Try logo path for the specific language and branch:
            logo_path = html_context.get("logo_path", {}).get(self.branch_name, {}).get(lang, None)
            if not logo_path:
                # Try just for the language:
                logo_path = html_context.get("logo_path", {}).get(lang, None)
                logo_extension = logo_path.split(".")[-1] if logo_path else None
            if logo_path:
                # Copy the logo to the expected location in the Sphinx source directory for that language
                cmd = ["sh", "-c", f"mkdir -p build/html/{self.branch_name}/{lang}/_static"]
                commands.append(cmd)
                logo_name = f"logo.{logo_extension}" if logo_extension else "logo.svg"
                cmd = ["sh", "-c", f"cp source/{logo_path} build/html/{self.branch_name}/{lang}/_static/{logo_name}"]
                commands.append(cmd)

            # Build the Sphinx documentation for this language
            ## Remove the https:// prefix for the -D html_baseurl parameter 
            ## since Sphinx expects a relative URL for correct link generation
            html_baseurl = self.doc_base_url.split("https://")[-1]
            cmd = ["sh", "-c", f". .venv/bin/activate && sphinx-build -b html -D language={lang} -D html_baseurl='{html_baseurl}' ./source ./build/html/{self.branch_name}/{lang}"]
            commands.append(cmd)

        # 4. Create index.html at the root of the HTML output that redirects to the default language (e.g., English) for convenience
        default_lang = html_context.get("default_language", "en")
        default_branch = html_context.get("default_branch", self.branch_name)
        if default_lang and default_branch:
            # 1. Get the template for the redirect index.html file and replace 
            # the placeholders in the template with the actual default branch and language
            redirect_index_html_str = self._generate_redirect_html(default_branch, default_lang)    

            ## 2. shlex.quote() safely wraps the string, automatically escaping 
            ## all internal quotes, spaces, and special characters for the shell.
            escaped_html = shlex.quote(redirect_index_html_str)

            # 3. Write index.html
            index_html_path = str(self.sphinx_dir / "build" / "html" / "index.html")
            cmd = ["sh", "-c", f"printf %s {escaped_html} > {index_html_path}"]
            commands.append(cmd)
        else:
            raise ValueError("Default language and default branch must be specified in the configuration to create the root index.html redirect page.")

        return {
            "branch": self.branch_name,
            "langs": langs,
            "commands": commands,
            "output_path": f"build/html/{self.branch_name}",
        }
    
    @typechecked
    def get_deploy_instructions(self, built_doc_path : str, publish_root_path : str ) -> list[list[str]]:
        """
        Generates the deployment strategy and agnostic Git commands.
        Commands are split into phases so runners can insert their own file-copy/mount 
        logic exactly where it belongs (between prepare and commit).
        """
        workdir_ph1 = publish_root_path
        cmds_ph1 = [
                # Phase 1: Clone the repository in workspace root
                # Clone the gh-pages branch if it exists, otherwise create an orphan branch. 
                # This ensures that we have a clean slate to work with in case of a new repositories.
                # But also have a doc that incorporates all the docs of all the brnanches having docs.
                f"git clone {self.auth_repo_url} --branch gh-pages --single-branch gh-pages || (git clone {self.auth_repo_url} gh-pages && cd gh-pages && git checkout --orphan gh-pages && find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {{}} ';')"
                ]
        
        cmds_ph1 = located_commands(cmds_ph1, workdir_ph1)

        cmds_ph2 = [
                # Phase 2: Clean old files from the branch (Run inside cloned directory)
                # and copy new ones from the build output
                f"rm -rf {self.branch_name} || true",
                f"shopt -s dotglob nullglob && mv {built_doc_path}/* . && shopt -u dotglob nullglob", # move all files including hidden ones but ignore if there is nothing to move
                "touch .nojekyll",
                ]
        
        workdir_ph2 = f"{publish_root_path}/gh-pages"
        cmds_ph2 = located_commands(cmds_ph2, workdir_ph2, shell="bash")
        

        workdir_ph3 = f"{publish_root_path}/gh-pages"
        cmds_ph3 = [
                # Phase 3: Commit and Push (Run inside cloned directory AFTER files are copied/mounted)
                f"git config --local user.email {self.action_email}",
                f"git config --local user.name {self.action_name}",
                "git add .",
                f"git commit -m 'Update documentation for {self.commit_hash}' -a || true",
                "git push origin gh-pages"
        ]
        cmds_ph3 = located_commands(cmds_ph3, workdir_ph3)

        if self.is_github:
            self.output_dir = f"{publish_root_path}/gh-pages"
            return cmds_ph1 + cmds_ph2 + cmds_ph3
        elif self.is_gitlab:
            # GitLab CI/CD can automatically deploy to GitLab Pages if the built files are placed in the correct directory (public/ by default).
            self.output_dir = str( self.gitlab_public_dir )
            # Copy all that is inside gh-pages except the .git directory to the public gitlab folder
            # the use of the -T option in cp and the shopt options in the mv command ensure that the contents of the built documentation are copied/moved directly into the target directory without creating an additional nested directory level, and that all files including hidden ones are included in the operation.
            cmd_clean = [
                f"mkdir -p {self.gitlab_public_dir}", # ensure the target directory exists before copying
                f"find . -mindepth 1 -maxdepth 1 ! -name .git -exec cp -rf {{}} {self.gitlab_public_dir}/ ';'"
                ]
            cmd_clean = located_commands(cmd_clean, workdir_ph3)
            return cmds_ph1 + cmds_ph2 + cmds_ph3 + cmd_clean
        else:
            # Put anything in "test/ci_cd/local_build_docs" folder but do not commit
            self.output_dir = str( (self.root_dir / "test" / "ci_cd" / "local_build_docs").resolve() )
            cmds_mv = [
                f"mkdir -p {self.output_dir}",
                f"find . -mindepth 1 -maxdepth 1 ! -name .git -exec mv {{}} {self.output_dir}/ ';'"
                ]
            cmds_mv = located_commands(cmds_mv, workdir_ph3)
            # remove the cloned repo to clean and avoid confusion
            cmd_rm = ["sh", "-c", f"rm -rf {publish_root_path}/gh-pages"]
            return cmds_ph1 + cmds_ph2 + cmds_mv + [cmd_rm]

    @typechecked
    def _run_local_git(self, command: list[str]) -> str:
        cmd = " ".join(command)
        try:
            result = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.PIPE, cwd=self.root_dir).strip()
            return result
        except subprocess.CalledProcessError as e:
            return ""
        
    @typechecked
    def get_branch_cmd() -> list[str]:
        return ["git", "branch", "--show-current"]

    @typechecked
    async def get_branch_name(self) -> str:
        if self.is_github:
            return os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "main")
        elif self.is_gitlab:
            return os.environ.get("CI_COMMIT_REF_NAME", "main")
        else:
            try:
                b = await self._exec_git(CIDocContext.get_branch_cmd())
                return b.strip() if b else "local-dev"
            except Exception as e:
                print(f"WARNING: Failed to get branch name from local git command: {e}")
                return "local-dev"
    
    @typechecked
    def get_commit_hash_cmd() -> list[str]:
        return ["git", "rev-parse", "HEAD"]
    
    @typechecked
    def valid_hash(self, hash: str|None) -> str:
        if not hash:
            return f"local-build-{time.strftime('%Y%m%d-%H%M%S')}"
        return hash

    @typechecked
    async def get_commit_hash(self) -> str:
        if self.is_github:
            return os.environ.get("GITHUB_SHA", "unknown")
        elif self.is_gitlab:
            return os.environ.get("CI_COMMIT_SHA", "unknown")
        try:
            hash_val = await self._exec_git(CIDocContext.get_commit_hash_cmd())
            hash_val = hash_val.strip() if hash_val else None
        except Exception as e:
            print(f"WARNING: Failed to get commit hash from local git command: {e}")
            hash_val = None
        return self.valid_hash(hash_val)
    
    @typechecked
    def get_repo_remote_cmd() -> list[str]:
        return ["git", "config", "--get", "remote.origin.url"]
    
    @typechecked
    async def get_remote(self) -> str:
        remote = None
        try:
            remote = await self._exec_git(CIDocContext.get_repo_remote_cmd())
            remote = remote.strip() if remote else None
        except Exception as e:
            print(f"WARNING: Failed to get git remote from local git command: {e}")
        return remote if remote else ""
    
    @typechecked
    def get_project_name(self) -> str:
        if self.is_github:
            return os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
        elif self.is_gitlab:
            return os.environ.get("CI_PROJECT_NAME", "unknown-project")
        url = self.remote
        return url.split("/")[-1].replace(".git", "") if url else self.root_dir.name

    @typechecked
    def _get_repo_url(self) -> str:
        url = ""
        if self.is_github:
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            url = f"https://github.com/{repo}" if repo else ""
        elif self.is_gitlab:
            url = os.environ.get("CI_REPOSITORY_URL", "")
        else:
            url = self.remote       
        if url and url.startswith("git@"):
            url = url.replace(":", "/").replace("git@", "https://")
        return url.replace(".git", "") if url else ""
    
    @typechecked
    def _get_gitlab_doc_base_url(self) -> str | None:    
        """Helper to construct the base URL for GitLab Pages documentation based on the repository URL."""
        if self.repo_url:
            # Assuming GitLab url structure: 
            #    https://gitlab.com/[username|groupname]/subgroup1/subgroup2/.../repo
            # Assuming GitLab Pages structure: 
            #    https://[username|groupname].pages.domain/subgroup1/subgroup2/.../[projectname]
            # where domain is the GitLab instance domain (e.g., gitlab.io)
            try:
                url_path = self.repo_url.split("https://")[-1].split("/")
                domain_name = url_path[0]
                domain_name_list = domain_name.split(".")
                if len(domain_name_list) >= 2:
                    domain = ".".join(domain_name_list[-2:])
                else:
                    domain = domain_name
                username_or_group = url_path[1]
                reponame = url_path[-1]
                subgroups = "/".join(url_path[2:-1])
                if subgroups:
                    return f"https://{username_or_group}.pages.{domain}/{subgroups}/{reponame}"
                else:
                    return f"https://{username_or_group}.pages.{domain}/{reponame}"
            except Exception as e:
                print(f"WARNING: Failed to construct GitLab Pages URL from repo URL '{self.repo_url}': {e}")
                return None
        return None

    @typechecked
    def _get_doc_base_url(self) -> str | None:
        if self.is_github and self.repo_url:
            # Assuming GitHub url structure: https://github.com/username/repo
            # Assuming GitHub Pages structure: https://username.github.io/repo
            parts = self.repo_url.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                username = parts[0]
                reponame = parts[1]
                return f"https://{username}.github.io/{reponame}"
            else:
                raise ValueError(f"ERROR: Unexpected GitHub repository URL format: {self.repo_url}")
        elif self.repo_url:
            # check_environment() shows strange value for CI_PAGES_URL in GitLab CI/CD, so we construct the URL based on the repository URL and known GitLab Pages patterns instead of relying on the environment variable.
            # return os.environ.get("CI_PAGES_URL")
            # Assuming this is a GitLab hosted project
            return self._get_gitlab_doc_base_url()
        # Strictly returning None for local builds without a remote
        return None

    @typechecked
    def _generate_redirect_html(self, default_branch: str, default_lang: str) -> str:
        """Generates the HTML redirect template by reading the external template file."""
        template_path = self.package_dir / "index.template.html"
        if template_path.exists():
            with open(template_path, "r") as f:
                template = f.read()
            
            # Safely handle None to prevent "None/index.html" in the canonical link
            base_url_str = self.doc_base_url if self.doc_base_url else ""
            
            return template % {"BRANCH": default_branch, "LANG": default_lang, "BASE_URL": base_url_str}
        else:
            raise FileNotFoundError(f"CRITICAL: Template not found at {template_path}")
    
    @typechecked
    def check_environment(self) -> None:
        """
        Check and display all environment variables that the script may use.
        Prints a formatted table showing which variables are set and their values.
        """
        print("\n" + "="*90)
        print("ENVIRONMENT VARIABLES CHECK")
        print("="*90 + "\n")

        print(f"Branch: {self.branch_name}")
        print(f"Commit Hash: {self.commit_hash}")
        print(f"Remote: {self.remote}")
        print(f"Project Name: {self.project_name}")
        print(f"Repo URL: {self.repo_url}")
        print(f"Documentation Base URL: {self.doc_base_url}")
        print(f"Authenticated Repo URL: {self.auth_repo_url}")
        print(f"Git User Email: {self.action_email}")
        print(f"Git User Name: {self.action_name}")
        
        for platform, variables in ENVIRONMENT_VARIABLES.items():
            print(f"{platform}:")
            print("-" * 90)
            
            # Header
            print(f"{'Variable Name':<30} {'Status':<10} {'Value':<50}")
            print("-" * 90)
            
            # Check each variable
            for var_name, description in variables.items():
                value = os.environ.get(var_name)
                if value:
                    status = "✓ Found"
                    # Mask sensitive values
                    display_value = value if "TOKEN" not in var_name else "***" + value[-4:] if len(value) > 4 else "***"
                else:
                    status = "✗ Missing"
                    display_value = "(not set)"
                
                print(f"{var_name:<30} {status:<10} {display_value:<50}")
            
            print()
    
        print("="*90)
        print("Note: ✓ = Variable is set, ✗ = Variable is missing")
        print("="*90 + "\n")

def get_sync_doc_context(root_dir: str | Path, run_local_git_commands: Callable[[list[str]], str | Awaitable[str]] | None = None) -> CIDocContext:
    """
    Factory function to create and initialize the CIDocContext.
    Use only in a synchronous context (e.g., Invoke).
    """

    # Check if there is a running event loop to determine if we are in an async context
    try:
        asyncio.get_running_loop()
        is_async = True
    except RuntimeError:
        is_async = False

    if is_async:
        raise RuntimeError("ERROR: get_sync_doc_context() cannot be called from an async context. In that case use:\n"
                           "    ctx = CIDocContext(root_dir, run_local_git_commands)\n"
                           "    await ctx.setup()\n")
    
    # No running event loop, safe to proceed    
    context = CIDocContext(root_dir, run_local_git_commands)
    asyncio.run(context.setup())
    return context