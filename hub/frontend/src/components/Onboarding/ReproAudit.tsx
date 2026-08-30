import { CheckCircleIcon, WarningTwoIcon } from "@chakra-ui/icons"
import {
  Box,
  Code,
  Flex,
  Heading,
  Icon,
  SimpleGrid,
  Skeleton,
  Stat,
  StatLabel,
  StatNumber,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"

import { ProjectsService, type ReproCheck } from "../../client"

export interface AuditFinding {
  key: string
  ok: boolean
  title: string
  detail: string
  /** The files the finding is about, when naming them is the point. */
  paths?: string[]
}

/** How many paths a finding shows before folding the rest into "+N more". */
export const MAX_FINDING_PATHS = 5

/**
 * Turn a repro check into what a reader would say about the project.
 *
 * Good news first, then what it would take, in the order the work happens.
 */
export function auditFindings(check: ReproCheck): AuditFinding[] {
  const findings: AuditFinding[] = []
  findings.push({
    key: "pipeline",
    ok: check.has_pipeline && check.n_stages > 0,
    title:
      check.n_stages > 0
        ? `A pipeline with ${check.n_stages} ${
            check.n_stages === 1 ? "stage" : "stages"
          }`
        : "No pipeline yet",
    detail:
      check.n_stages > 0
        ? "Someone can rerun these in order without reading your notes."
        : "Nothing says which script runs first, or what each one produces. " +
          "A stage per script fixes that.",
  })
  const looseScripts = check.scripts_not_in_pipeline ?? []
  const nLooseScripts = check.n_scripts_not_in_pipeline ?? looseScripts.length
  findings.push({
    key: "scripts",
    ok: nLooseScripts === 0,
    title:
      nLooseScripts > 0
        ? `${nLooseScripts} ${
            nLooseScripts === 1 ? "script" : "scripts"
          } no stage runs`
        : "Every script runs from a stage",
    detail:
      nLooseScripts > 0
        ? "A reader can't tell whether these still matter or what order " +
          "they go in. Add a stage for each one that does, or delete the " +
          "rest."
        : "There's no script in the repo whose place in the process is a " +
          "mystery.",
    paths: looseScripts,
  })
  const withoutEnv = check.stages_without_env?.length ?? 0
  findings.push({
    key: "environment",
    ok: check.n_environments > 0 && withoutEnv === 0,
    title:
      check.n_environments === 0
        ? "No computational environment declared"
        : withoutEnv > 0
          ? `${withoutEnv} ${
              withoutEnv === 1 ? "stage runs" : "stages run"
            } outside any environment`
          : `${check.n_environments} ${
              check.n_environments === 1 ? "environment" : "environments"
            }, every stage in one`,
    detail:
      check.n_environments === 0
        ? "Which Python, which packages, which versions? Right now the " +
          "answer is whatever is on your laptop."
        : withoutEnv > 0
          ? `${check.stages_without_env.join(", ")}: pin what each one needs so it runs the same elsewhere.`
          : "Pinned, so it runs the same on a collaborator's machine.",
  })
  const looseData = check.n_datasets_no_import_or_stage
  findings.push({
    key: "dataset",
    ok: check.n_datasets > 0 && looseData === 0,
    title:
      check.n_datasets === 0
        ? "No datasets declared"
        : looseData > 0
          ? `${looseData} of ${check.n_datasets} datasets with no stated origin`
          : `${check.n_datasets} ${
              check.n_datasets === 1 ? "dataset" : "datasets"
            }, each with a source`,
    detail:
      check.n_datasets === 0
        ? "The data is in here somewhere. Say which files are data and " +
          "where they came from, and every figure can be traced back."
        : looseData > 0
          ? "Collected here, downloaded, from a DOI, or made by a stage: " +
            "say which, or a reader has to take the numbers on faith."
          : "A reader can follow any figure back to the data behind it.",
  })
  const looseFigs = check.n_figures_no_import_or_stage
  findings.push({
    key: "figure",
    ok: check.n_figures > 0 && looseFigs === 0,
    title:
      check.n_figures === 0
        ? "No figures declared"
        : looseFigs > 0
          ? `${looseFigs} of ${check.n_figures} figures not made by a stage`
          : `${check.n_figures} ${
              check.n_figures === 1 ? "figure" : "figures"
            }, all produced by the pipeline`,
    detail:
      check.n_figures === 0
        ? "Point at the images that go in the paper and the stage that " +
          "draws each one."
        : looseFigs > 0
          ? "A figure with no stage is a file someone once made. Attach " +
            "the stage, or record who drew it by hand."
          : "Change the data and the figures follow.",
  })
  const looseMisc = check.misc_needing_provenance ?? []
  const nLooseMisc = check.n_misc_needing_provenance ?? looseMisc.length
  findings.push({
    key: "misc",
    ok: nLooseMisc === 0,
    title:
      nLooseMisc > 0
        ? `${nLooseMisc} generated ${
            nLooseMisc === 1 ? "file" : "files"
          } with no stated origin`
        : "Every generated file says where it came from",
    detail:
      nLooseMisc > 0
        ? "Images, PDFs and the like that no stage produces, no import " +
          "records, and nobody claims. Name the stage that makes each " +
          "one, or record who made it and how."
        : "Nothing in the repo looks like output that came from nowhere.",
    paths: looseMisc,
  })
  findings.push({
    key: "publication",
    ok: check.n_publications > 0,
    title:
      check.n_publications > 0
        ? `${check.n_publications} ${
            check.n_publications === 1 ? "publication" : "publications"
          } linked`
        : "No paper linked",
    detail:
      check.n_publications > 0
        ? "The paper builds from the same pipeline as the figures in it."
        : "Connect the Overleaf project or start one here, so the figures " +
          "in it stop going stale.",
  })
  findings.push({
    key: "readme",
    ok: check.has_readme && check.instructions_in_readme,
    title: check.has_readme
      ? check.instructions_in_readme
        ? "README says how to run it"
        : "README, but no instructions to reproduce"
      : "No README",
    detail: check.instructions_in_readme
      ? "A stranger could start from the front page."
      : "With a pipeline in place the instructions are one line: " +
        "calkit run.",
  })
  return findings
}

interface ReproAuditProps {
  accountName: string
  projectName: string
}

/**
 * What we found in an imported project, and what's between it and
 * reproducible.
 *
 * This is the moment the "clean up a project in progress" path promised:
 * someone finally looked at the whole thing and said what's there. The
 * gaps become the project checklist, so nothing here is a dead end.
 */
const ReproAudit = ({ accountName, projectName }: ReproAuditProps) => {
  const okColor = "ui.success"
  const gapColor = useColorModeValue("orange.500", "orange.300")
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const checkQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "repro-check"],
    queryFn: () =>
      ProjectsService.getProjectReproCheck({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
    refetchOnWindowFocus: false,
  })
  if (checkQuery.isPending) {
    return (
      <Box>
        <Skeleton height="20px" mb={3} />
        <Skeleton height="20px" mb={3} />
        <Skeleton height="20px" />
      </Box>
    )
  }
  if (checkQuery.isError || !checkQuery.data) {
    return (
      <Text color="ui.dim">
        Couldn't read the project yet. It may still be importing; the project
        page will show the same summary once it's in.
      </Text>
    )
  }
  const check = checkQuery.data
  const findings = auditFindings(check)
  const gaps = findings.filter((f) => !f.ok)
  const stats = [
    { label: "Stages", value: check.n_stages },
    { label: "Environments", value: check.n_environments },
    { label: "Datasets", value: check.n_datasets },
    { label: "Figures", value: check.n_figures },
    { label: "Publications", value: check.n_publications },
  ]
  return (
    <Box>
      <SimpleGrid columns={{ base: 3, md: 5 }} spacing={3} mb={5}>
        {stats.map((stat) => (
          <Stat
            key={stat.label}
            borderWidth={1}
            borderColor={borderColor}
            bg={cardBg}
            borderRadius="md"
            px={3}
            py={2}
            size="sm"
          >
            <StatLabel fontSize="xs">{stat.label}</StatLabel>
            <StatNumber fontSize="xl">{stat.value}</StatNumber>
          </Stat>
        ))}
      </SimpleGrid>
      <Heading size="sm" mb={3}>
        {gaps.length === 0
          ? "This project is already in good shape"
          : `${gaps.length} ${
              gaps.length === 1 ? "thing" : "things"
            } between this project and reproducible`}
      </Heading>
      <Box>
        {findings.map((finding) => (
          <Flex key={finding.key} gap={3} mb={3} align="flex-start">
            <Icon
              as={finding.ok ? CheckCircleIcon : WarningTwoIcon}
              color={finding.ok ? okColor : gapColor}
              boxSize={4}
              mt={0.5}
            />
            <Box>
              <Text fontWeight="semibold" fontSize="sm">
                {finding.title}
              </Text>
              <Text fontSize="sm" color="ui.dim">
                {finding.detail}
              </Text>
              {!finding.ok && finding.paths?.length ? (
                <Flex gap={1} mt={1} wrap="wrap" align="center">
                  {finding.paths.slice(0, MAX_FINDING_PATHS).map((path) => (
                    <Code key={path} fontSize="xs">
                      {path}
                    </Code>
                  ))}
                  {finding.paths.length > MAX_FINDING_PATHS ? (
                    <Text fontSize="xs" color="ui.dim">
                      +{finding.paths.length - MAX_FINDING_PATHS} more
                    </Text>
                  ) : null}
                </Flex>
              ) : null}
            </Box>
          </Flex>
        ))}
      </Box>
    </Box>
  )
}

export default ReproAudit
