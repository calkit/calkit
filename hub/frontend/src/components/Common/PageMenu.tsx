import { Box, useColorModeValue } from "@chakra-ui/react"

interface PageMenuProps {
  children: React.ReactNode
}

const PageMenu = ({ children }: PageMenuProps) => {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  return (
    <Box
      position="sticky"
      top={0}
      maxW="300px"
      minW="200px"
      maxH="100%"
      overflowY="auto"
      alignSelf="flex-start"
      px={3}
      py={2}
      mr={6}
      mt={0}
      borderRadius="lg"
      borderWidth={0}
      bg={secBgColor}
      boxSizing="border-box"
    >
      {children}
    </Box>
  )
}

export default PageMenu
