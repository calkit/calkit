import { createFileRoute } from "@tanstack/react-router"
import { Box, Container, Heading, Link, Text } from "@chakra-ui/react"

export const Route = createFileRoute("/_layout/learn")({
  component: Learn,
})

function Learn() {
  return (
    <Container maxW="800px">
      <Heading size="lg" textAlign={{ base: "center", md: "left" }} pt={12}>
        Learn
      </Heading>
      <Box pt={5}>
        <Text mb={4}>
          To effectively use Calkit, you're going to want to{" "}
          <Link
            variant="blue"
            isExternal
            href="https://github.com/calkit/calkit?tab=readme-ov-file#installation"
          >
            install the command line interface (CLI)
          </Link>
          .
        </Text>
        <Text mb={4}>
          After that check out the{" "}
          <Link
            isExternal
            variant="blue"
            href="https://docs.calkit.org/tutorials/"
          >
            tutorials
          </Link>
          .
        </Text>
        <Text mb={4}>
          If you notice a bug or have a suggestion for a new feature, submit a
          new issue to the{" "}
          <Link
            variant="blue"
            isExternal
            href="https://github.com/calkit/calkit/issues"
          >
            issue tracker
          </Link>
          .
        </Text>
        <Text mb={4}>
          Lastly, get in touch with the community on the{" "}
          <Link
            variant="blue"
            isExternal
            href="https://github.com/orgs/calkit/discussions"
          >
            discussion forum
          </Link>{" "}
          or on{" "}
          <Link isExternal variant="blue" href="https://discord.gg/uhtbgXUu">
            Discord
          </Link>
          .
        </Text>
        <Text mb={4}>
          If you want to get in touch directly, send us an{" "}
          <Link isExternal variant="blue" href="mailto:feedback@calkit.io">
            email
          </Link>
          .
        </Text>
      </Box>
    </Container>
  )
}
