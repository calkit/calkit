# Contributing to Calkit

Thank you for considering contributing to Calkit!
We welcome contributions of all kinds, including code, documentation,
bug reports, and feature suggestions.
This guide will help you get started.

## 🛠 How to contribute

### 1. Find an issue to work on

- Check the **[backlog](https://github.com/orgs/calkit/projects/1/views/1)**
  for issues that are ready to be worked on.
- Look for issues labeled `good first issue` if you're new.
- If you have an idea, open a new issue and discuss it before coding.

### 2. Set up your development environment

1. [**Fork** the repository](https://github.com/calkit/calkit/fork).
1. **Clone** your fork locally:
   ```bash
   git clone https://github.com/{your-username}/calkit.git
   cd calkit
   ```
1. **Install system-level dependencies:**
   - [Docker](https://docker.com)
   - [Miniforge](https://conda-forge.org/download/)
   - [uv](https://docs.astral.sh/uv/getting-started/installation/)
   - [Pixi](https://pixi.sh/latest/)
1. **Run tests** to ensure everything is working:
   ```bash
   uv run pytest
   ```

### 3. Make your changes

- Create a new branch:
  ```bash
  git checkout -b your-feature-name
  ```
- Check and fix code formatting:
  ```bash
  make format
  ```
- Commit your changes
  (use the imperative mood and capitalize the first letter,
  but don't use punctuation):
  ```bash
  git add .
  git commit -m "Short description of your change"
  ```
- Push your branch:
  ```bash
  git push origin your-feature-name -u
  ```

### 4. Submit a pull request (PR)

- Open a **Pull request** on GitHub.
- Link the PR to the issue it resolves by adding "resolves #{issue number}"
  to the description.
- Wait for a review and make necessary changes.

## 💡 Other ways to contribute

- **Report bugs**: Open an issue with detailed reproduction steps.
- **Improve documentation**: Help us make Calkit's docs better.
- **Suggest features**: Share your ideas for improvements.

## 🎉 Join the community

- Participate in **[GitHub Discussions](https://github.com/calkit/discussions)**.
- Join our [**Discord**](https://discord.gg/ubb7gAXc) for real-time collaboration.
- Follow our updates on [**LinkedIn**](https://linkedin.com/company/calkit).

We appreciate your help in making Calkit better! 🚀
