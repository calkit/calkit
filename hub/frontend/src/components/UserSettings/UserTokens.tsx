import {
  Button,
  Checkbox,
  Container,
  Heading,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { type TokenPatch, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import NewToken from "./NewToken"

function UserTokens() {
  const queryClient = useQueryClient()
  const tokensQuery = useQuery({
    queryKey: ["user", "tokens"],
    queryFn: () =>
      UsersService.getUserTokens().then((response) => response.data),
  })
  interface TokenIsActive {
    tokenId: string
    tokenPatch: TokenPatch
  }
  const tokenActiveMutation = useMutation({
    mutationFn: ({ tokenId, tokenPatch }: TokenIsActive) =>
      UsersService.patchUserToken({
        tokenPatch: tokenPatch,
        token_id: tokenId,
      }).then((response) => response.data),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["user", "tokens"] }),
  })
  const newTokenModal = useDisclosure()
  const showToast = useCustomToast()
  const endSessionsMutation = useMutation({
    mutationFn: () => UsersService.postUserSessionsEndOthers(),
    onSuccess: () =>
      showToast("Success!", "Signed out of other sessions.", "success"),
    onError: (e: any) =>
      showToast("Error", e.response?.data?.detail ?? e.message, "error"),
  })

  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Tokens
      </Heading>
      <Button variant={"primary"} mb={4} onClick={newTokenModal.onOpen}>
        Create new token
      </Button>
      <NewToken isOpen={newTokenModal.isOpen} onClose={newTokenModal.onClose} />
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>ID</Th>
              <Th>Description</Th>
              <Th>Created</Th>
              <Th>Expires</Th>
              <Th>Scope</Th>
              <Th>Active</Th>
            </Tr>
          </Thead>
          {tokensQuery.isPending || tokenActiveMutation.isPending ? (
            <Tbody>
              <Tr>
                {new Array(5).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {tokensQuery.data?.map((token) => (
                <Tr
                  key={token.id}
                  opacity={tokensQuery.isPlaceholderData ? 0.5 : 1}
                >
                  <Td isTruncated maxWidth="100px">
                    {token.id}
                  </Td>
                  <Td isTruncated maxWidth="200px">
                    {token.description}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {token.created}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {token.expires}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {token.scope ? token.scope : ""}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    <Checkbox
                      isChecked={token.is_active}
                      isDisabled={tokenActiveMutation.isPending}
                      onChange={(e) =>
                        tokenActiveMutation.mutate({
                          tokenId: String(token.id),
                          tokenPatch: { is_active: e.target.checked },
                        })
                      }
                    />
                  </Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      <Heading size="md" pt={8} pb={4}>
        Sessions
      </Heading>
      <Text mb={4}>
        Sign out everywhere except this browser. Tokens stay active.
      </Text>
      <Button
        variant="outline"
        isLoading={endSessionsMutation.isPending}
        onClick={() => endSessionsMutation.mutate()}
      >
        Sign out other sessions
      </Button>
    </Container>
  )
}

export default UserTokens
