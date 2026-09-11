import { Box, Flex, Link, Text, Code, Heading } from "@chakra-ui/react"
import { Link as RouterLink, getRouteApi } from "@tanstack/react-router"

// Stage status colors -- must match _MERMAID_STYLES (backend app/pipeline.py)
// so the legend matches the diagram.
const PIPELINE_LEGEND: { color: string; label: string; desc: string }[] = [
  {
    color: "#1f5a1f",
    label: "Up to date",
    desc: "outputs match the current inputs and code",
  },
  {
    color: "#8a6a00",
    label: "Stale",
    desc: "inputs or code changed since it last ran; re-run to refresh",
  },
  {
    color: "#3a3a3a",
    label: "Not run",
    desc: "has never produced its outputs",
  },
  {
    color: "#1a4f7a",
    label: "Always run",
    desc: "re-executes every time by design",
  },
  {
    color: "#5e7d8a",
    label: "Frozen",
    desc: "is not re-run even if inputs change",
  },
]

interface HelpContentProps {
  userHasWriteAccess: boolean
}

// Shown on both the project home and the Releases page so the concept is
// discoverable from either help drawer.
function ReleasesHelp({ mb }: { mb: number }) {
  return (
    <Text mb={mb}>
      When you want to share part or all of your project with the outside world,
      create a release. These can be internal, which means they remain in Calkit
      only (useful for sharing with collaborators who mainly act as reviewers),
      or they can be external, uploaded to a permanent archival service like
      Figshare, Zenodo, or CaltechDATA. You can also list releases to journals
      or arXiv here to keep track of which exact versions made it where.
    </Text>
  )
}

function HelpContent({ userHasWriteAccess }: HelpContentProps) {
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const page = location.pathname.split("/").at(-1)
  const mb = 4
  if (page === "files") {
    return (
      <>
        <Text mb={mb}>
          This view shows the full project working directory, including files
          tracked by Git (typically text files like code and Markdown documents)
          and files tracked by DVC, e.g., datasets, figure PDFs or PNGs, etc.
          Note that files tracked with DVC are typically larger, and are not
          populated on your local machine when cloning the project repo. These
          can be fetched with <Code>dvc pull</Code>.
        </Text>
        <Text>
          Artifacts labeled with Calkit are highlighted with a green icon.
          Labeling artifacts is a way to clarify "special" files or folders that
          have a specific meaning to the project. For example, a certain folder
          may contain an important dataset used in the pipeline to produce a
          certain figure, which is also labeled as a <Code>figure</Code>{" "}
          artifact.
        </Text>
      </>
    )
  }
  if (page === "app") {
    return (
      <>
        <Text mb={mb}>
          It's possible to define an interactive web app for your project, e.g.,
          so others can make useful predictions from or better understand your
          findings.
        </Text>
        <Text>
          To add an app, create one on{" "}
          <Link isExternal variant="blue" href="https://huggingface.co/spaces">
            HF Spaces
          </Link>{" "}
          and set the <Code>app.url</Code> in your project's{" "}
          <Code>calkit.yaml</Code> file to the HF Spaces embed URL.
        </Text>
      </>
    )
  }
  // Publications help
  if (page === "publications") {
    return (
      <>
        <Text mb={mb}>
          Publications are used to provide a summary of the project and its
          findings. Typically these are the "interface" that others will
          interact with first before diving deeper into the rest of the
          project's artifacts. It's typically a good idea to share a publication
          PDF as a released artifact so it's clear exactly what snapshot of the
          project produced it, so other can trace back through the pipeline to
          see how all of the evidence (e.g., figures) was generated.
        </Text>
      </>
    )
  }
  if (page === "environments") {
    return (
      <>
        <Text mb={mb}>
          Environments describe the dependencies (apps, packages, libraries)
          necessary to execute a computational process. These can be created or
          defined with a variety of different environment management tools,
          e.g., Conda, Docker, uv, venv, Renv, etc.
        </Text>
        <Text mb={mb}>
          Ideally, each stage in the pipeline is executed within one of these
          environments so dependencies don't need to be installed system-wide,
          which can result in conflicts. Furthermore, Calkit will automatically
          ensure an environment matches its spec at run time, saving you the
          mental bandwidth.
        </Text>
        <Text mb={mb}>
          On this page you can view the environments defined for a project, view
          their specification, and reuse one in a project of your own.
        </Text>
      </>
    )
  }
  if (page === "figures") {
    return (
      <>
        <Text mb={mb}>
          Figures are visualizations of data or results. These will typically be
          produced in pipeline stages with datasets and code as their
          dependencies so they can be easily reproduced or updated if their
          dependencies change. They will also typically be inserted into
          publications.
        </Text>
        <Text mb={mb}>
          To create a new figure, either upload a new file or label an existing
          file by clicking the <Code>+</Code> button to the left. Alternatively,
          it is possible to add a figure by editing the project's{" "}
          <Code>calkit.yaml</Code> file.
        </Text>
      </>
    )
  }
  if (page === "data" || page === "datasets") {
    return (
      <>
        <Text mb={mb}>
          Datasets can be produced as part of a project or imported from a
          different project for further synthesis and analysis. They are
          typically dependencies and/or outputs in the pipeline. An output
          dataset might be produced as part of a pipeline stage that reduced
          some raw data. A dataset that is merely a dependency could be produced
          as part of an experiment's data collection process.
        </Text>
        <Text mb={mb}>
          Labeling a file or folder as a dataset helps clarify its purpose, and
          if the project is open to the public, helps facilitate its reuse in
          further studies.
        </Text>
        <Text mb={mb}>
          To create a new dataset, either upload a new file or label an existing
          file or folder by clicking the <Code>+</Code> button to the left.
          Alternatively, it is possible to label a dataset by editing the
          project's <Code>calkit.yaml</Code> file.
        </Text>
      </>
    )
  }
  if (page === "pipeline") {
    return (
      <>
        <Text mb={mb}>
          The project's pipeline describes the steps (or "stages") taken to
          produce all of the desired outputs. For example, one stage could
          involve processing the raw data. Another could create a figure from
          these. Another could produce a publication. The pipeline can be run
          locally by executing <Code>calkit run</Code> in the project working
          directory.
        </Text>
        <Text mb={mb}>
          For instructions on how to create your pipeline, see the{" "}
          <Link
            isExternal
            variant="blue"
            href="https://docs.calkit.org/pipeline/"
          >
            pipeline documentation
          </Link>
          .
        </Text>
        <Text mb={2}>In the diagram, each stage is colored by its status:</Text>
        <Box mb={mb}>
          {PIPELINE_LEGEND.map((item) => (
            <Flex key={item.label} align="baseline" gap={2} mb={1}>
              <Box
                boxSize={3}
                borderRadius="sm"
                bg={item.color}
                flexShrink={0}
                transform="translateY(1px)"
              />
              <Text fontSize="sm">
                <b>{item.label}</b>: {item.desc}.
              </Text>
            </Flex>
          ))}
        </Box>
      </>
    )
  }
  if (page === "collaborators") {
    return (
      <>
        <Text mb={mb}>
          Collaborators are other users who can edit your project. This means
          the are able to clone the Git repo, push changes to GitHub, etc.
        </Text>
      </>
    )
  }
  if (page === "references") {
    return (
      <>
        <Text mb={mb}>
          On this page you can view references added to your project. These
          references are part of collections in BibTeX files. To add references
          to a collection, edit the BibTeX file directly. To add a new
          collection, add a BibTeX file to the project repo and add it to the{" "}
          <Code>references</Code> section of the <Code>calkit.yaml</Code> file.
        </Text>
      </>
    )
  }
  if (page === "notebooks") {
    return (
      <>
        <Text mb={mb}>
          This page is dedicated to the project's{" "}
          <Link isExternal variant="blue" href="https://jupyter.org/">
            Jupyter notebooks
          </Link>
          . It is possible to define a pipeline stage that executes a notebook
          and converts it to a different format, e.g., HTML, which will be shown
          here if configured.
        </Text>
      </>
    )
  }
  if (page === "presentations") {
    return (
      <>
        <Text mb={mb}>
          Presentations are artifacts used to support interactive discussions on
          the project's findings. These can be produced with LaTeX (Beamer),
          Quarto, or PowerPoint. It's usually a good idea to share the PDF of
          these as part of a release so it's clear exactly what snapshot of
          files produced it.
        </Text>
      </>
    )
  }
  if (page === "releases") {
    return <ReleasesHelp mb={mb} />
  }
  if (page === "software") {
    return (
      <>
        <Text mb={mb}>
          This page serves as an index for software created for and/or used in
          the project, which includes environments, packages or libraries, apps,
          and scripts. The main purpose of including this information is to
          ensure anything produced with the software can be reproduced. A
          secondary purpose is to make it easier for others to use the software
          in their own projects by importing into them.
        </Text>
      </>
    )
  }
  if (page === "local") {
    return (
      <>
        <Text mb={mb}>
          This page provides an interface for interacting with the project
          working directory on your local machine. For this to work, the local
          Calkit server must be running. To start one up, run{" "}
          <Code>calkit local-server</Code> in a terminal after installing the{" "}
          <Link
            href="https://github.com/calkit/calkit"
            variant="blue"
            isExternal
          >
            Calkit Python package
          </Link>
          .
        </Text>
      </>
    )
  }
  // Default project home help content
  return (
    <>
      {userHasWriteAccess ? (
        <Text mb={mb}>
          Welcome to your Calkit project! To get started, try adding some{" "}
          questions you'd like to answer, or start defining the{" "}
          <Link
            as={RouterLink}
            to={`/${accountName}/${projectName}/pipeline`}
            variant="blue"
          >
            pipeline
          </Link>{" "}
          for how you'd like your outputs or artifacts to be created.
        </Text>
      ) : (
        ""
      )}
      <Text mb={mb}>
        To clone this project to your local machine, navigate into a folder in
        which you'd like to store Calkit projects, e.g., <Code>~/calkit</Code>{" "}
        and execute:
      </Text>
      <Code whiteSpace="pre" overflow="auto" mb={mb} width="100%" p={2}>
        calkit clone {accountName}/{projectName}
      </Code>
      {/* Questions help */}
      <Heading size="md" mb={mb / 2}>
        Questions
      </Heading>
      <Text mb={mb}>
        Research projects are typically driven by one or more questions. Add
        these to the questions section and then tie back outputs as evidence to
        support answers to them.
      </Text>
      {/* Releases help */}
      <Heading size="md" mb={mb / 2}>
        Releases
      </Heading>
      <ReleasesHelp mb={mb} />
    </>
  )
}

export default HelpContent
