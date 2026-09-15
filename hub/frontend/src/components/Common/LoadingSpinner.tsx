import { Flex, Spinner } from "@chakra-ui/react"

interface LoadingSpinnerProps {
  height?: string
  width?: string
}

export default function LoadingSpinner({
  height = "full",
  width = "full",
}: LoadingSpinnerProps) {
  return (
    <Flex justify="center" align="center" height={height} width={width}>
      <Spinner size="xl" color="ui.main" />
    </Flex>
  )
}
