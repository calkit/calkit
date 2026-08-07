# The Calkit hub

A hub is where Calkit projects are shared, backed up, and collaborated
on. It serves as an index for projects and their artifacts
such as datasets, figures, publications, computational environments, etc.
It also serves as a [DVC](https://dvc.org) remote,
neatly integrated with the Calkit CLI
(which lives at the root of this repo),
so users can easily
back up their data and artifacts in the same repository as their code,
documentation, other text files, etc.
The main hub is [calkit.io](https://calkit.io).

The goal is that this can serve as a platform for working
efficiently and reproducibly, collaborating, and sharing all in one.
Our future vision is one where research is advanced more quickly
because instead of simply producing a paper,
other more reusable artifacts are created and can be easily carried forward
in new projects.
Additionally, all studies should be able to be reproduced by anyone else
by using this framework,
resulting in more reliable knowledge.

## Get involved

We welcome all kinds of contributions.

- Participate in **[GitHub Discussions](https://github.com/calkit/discussions)**.
- Join our [**Discord**](https://discord.gg/ubb7gAXc) for real-time collaboration.
- Follow our updates on [**LinkedIn**](https://linkedin.com/company/calkit).

## Deploying your own hub

A future goal of this project is to make it easy for teams or institutions
to deploy their own hubs in a federated network, where users on
any hub can search for projects, datasets, etc., on any other hub.
This is currently not easy
(see [Running your own hub](https://docs.calkit.org/hub/self-hosting/)
for the current state), but if you'd like to help make it so, please
join the discussion in
[this issue](https://github.com/calkit/calkit-cloud/issues/190).

## Technology stack and features

This project was derived from
[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) by Sebastián Ramírez,
which uses:

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend API.
    - 🧰 [SQLModel](https://sqlmodel.tiangolo.com) for the Python SQL database interactions (ORM).
    - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
    - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
- 🚀 [React](https://react.dev) for the frontend.
    - 💃 Using TypeScript, hooks, Vite, and other parts of a modern frontend stack.
    - 🎨 [Chakra UI](https://chakra-ui.com) for the frontend components.
    - 🤖 An automatically generated frontend client.
    - 🧪 [Playwright](https://playwright.dev) for End-to-End testing.
    - 🦇 Dark mode support.
- 🐋 [Docker Compose](https://www.docker.com) for development and production.
- 🔒 Secure password hashing by default.
- 🔑 JWT (JSON Web Token) authentication.
- 📫 Email based password recovery.
- ✅ Tests with [Pytest](https://pytest.org).
- 📞 [Traefik](https://traefik.io) as a reverse proxy / load balancer.
- 🚢 Deployment instructions using Docker Compose, including how to set up a frontend Traefik proxy to handle automatic HTTPS certificates.
- 🏭 CI (continuous integration) and CD (continuous deployment) based on GitHub Actions.

## Backend development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend development

Frontend docs: [frontend/README.md](./frontend/README.md).

## Deployment

Deployment docs: [deployment.md](./docs/dev/deployment.md).

## Development

General development docs: [development.md](./docs/dev/development.md).

This includes using Docker Compose, custom local domains, `.env`
configurations, etc.
