# ============================================================================
# Environment Variables Configuration
# ============================================================================
ENVIRONMENT_VARIABLES = {
    "GitHub Actions": {
        "GITHUB_ACTIONS": "Set to 'true' when running in GitHub Actions environment",
        "GITHUB_REPOSITORY": "Repository name in format 'owner/repo'",
        "GITHUB_SHA": "The commit SHA that triggered the workflow",
        "GITHUB_HEAD_REF": "The head branch name (for pull requests)",
        "GITHUB_REF_NAME": "The branch name (for push events)",
    },
    "GitLab CI": {
        "GITLAB_CI": "Set to 'true' when running in GitLab CI environment",
        "CI_PROJECT_NAME": "The project name",
        "CI_COMMIT_SHA": "The commit SHA",
        "CI_COMMIT_REF_NAME": "The branch name",
        "CI_REPOSITORY_URL": "The repository URL",
        "CI_PAGES_URL": "The GitLab Pages URL (optional)",
    },
}