# Release Process

This repository uses automated GitHub Actions workflows for building, testing, and publishing releases.

## Automated Workflows

### 1. Test Build (`test-build.yml`)
**Triggers:** Pull requests and pushes to main branch
- ✅ Tests package building
- ✅ Validates package integrity with `twine check`
- ✅ Tests installation
- 🧪 Publishes test versions to TestPyPI (main branch only)

### 2. PyPI Publication (`publish-to-pypi.yml`)
**Triggers:** GitHub releases
- 🚀 Automatically publishes to PyPI when a release is created
- 📦 Builds both wheel and source distributions
- ✅ Updates version numbers from Git tag
- 🔐 Uses trusted publishing (no API keys needed)

### 3. Create Release (`create-release.yml`)
**Triggers:** Manual workflow dispatch
- 🏷️ Creates Git tags and GitHub releases
- 📝 Auto-generates changelog from commits
- 🔄 Updates version in code files
- ⚡ Triggers automatic PyPI publication

## Setup Requirements

### 1. Configure PyPI Trusted Publishing

1. Go to [PyPI Trusted Publishing](https://pypi.org/manage/account/publishing/)
2. Add a new publisher with these settings:
   - **PyPI Project Name:** `dtop`
   - **Owner:** `StakeSquid` (or your GitHub username)
   - **Repository:** `dtop`
   - **Workflow:** `publish-to-pypi.yml`
   - **Environment:** `release`

3. For TestPyPI (optional):
   - Go to [TestPyPI Trusted Publishing](https://test.pypi.org/manage/account/publishing/)
   - Add publisher with environment: `test-release`

### 2. Create GitHub Environments

1. Go to your repository **Settings** → **Environments**
2. Create environment: `release`
   - Add protection rules (require reviewers for production releases)
3. Create environment: `test-release` (for TestPyPI)

## How to Release

### Method 1: Using the Automated Workflow (Recommended)

1. Go to **Actions** tab in GitHub
2. Select **"Create Release"** workflow
3. Click **"Run workflow"**
4. Fill in:
   - **Version:** e.g., `1.0.2`
   - **Release type:** patch/minor/major
   - **Pre-release:** check if this is a beta/alpha
5. Click **"Run workflow"**

The workflow will:
- ✅ Validate version format
- ✅ Update version in code files
- ✅ Commit changes
- ✅ Create Git tag
- ✅ Create GitHub release with auto-generated changelog
- 🚀 Trigger automatic PyPI publication

### Method 2: Manual Release

1. **Update version numbers:**
   ```bash
   # Update pyproject.toml
   sed -i 's/version = ".*"/version = "1.0.2"/' pyproject.toml
   
   # Update dtop/__init__.py
   sed -i 's/__version__ = ".*"/__version__ = "1.0.2"/' dtop/__init__.py
   ```

2. **Commit and tag:**
   ```bash
   git add pyproject.toml dtop/__init__.py
   git commit -m "Bump version to 1.0.2"
   git tag -a v1.0.2 -m "Release v1.0.2"
   git push origin main --tags
   ```

3. **Create GitHub release:**
   - Go to **Releases** → **Create a new release**
   - Select tag: `v1.0.2`
   - Auto-generate release notes
   - Publish release

## Version Numbering

Follow [Semantic Versioning](https://semver.org/):
- **Patch** (1.0.1): Bug fixes, documentation updates
- **Minor** (1.1.0): New features, backwards compatible
- **Major** (2.0.0): Breaking changes

## Monitoring Releases

- **Build Status:** Check Actions tab for workflow status
- **PyPI Publication:** View at https://pypi.org/project/dtop/
- **TestPyPI:** View at https://test.pypi.org/project/dtop/

## Troubleshooting

### Failed PyPI Publication
- Check trusted publishing configuration
- Verify environment name matches workflow
- Ensure version number doesn't already exist

### Version Conflicts
- Use `pip install --upgrade dtop` to get latest version
- Check if version exists: `pip show dtop`

### Workflow Failures
- Check Actions tab for detailed logs
- Verify all required secrets/environments are configured
- Ensure branch protection rules allow automated commits