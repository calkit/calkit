import {
  Container,
  Heading,
  Link,
  Radio,
  RadioGroup,
  Stack,
  Text,
} from "@chakra-ui/react"
import { useSyncExternalStore } from "react"

import {
  type AnalyticsConsent,
  analyticsEnabled,
  getAnalyticsConsent,
  privacyPolicyUrl,
  setAnalyticsConsent,
  subscribeAnalyticsConsent,
} from "../../lib/analytics"

const Privacy = () => {
  // Saving to the account happens in the layout, which watches this too
  const consent = useSyncExternalStore(
    subscribeAnalyticsConsent,
    getAnalyticsConsent,
  )

  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Usage analytics
      </Heading>
      {analyticsEnabled ? (
        <>
          <Text fontSize="sm" mb={4}>
            Calkit can record which pages you visit and which features you use,
            so we can improve useful ones and remove the rest. Your data is
            never sold or used for advertising. See the{" "}
            <Link href={privacyPolicyUrl} isExternal textDecoration="underline">
              privacy policy
            </Link>{" "}
            for details.
          </Text>
          <RadioGroup
            value={consent ?? ""}
            onChange={(value) => setAnalyticsConsent(value as AnalyticsConsent)}
          >
            <Stack>
              <Radio value="granted" colorScheme="teal">
                Allow analytics
              </Radio>
              <Radio value="denied" colorScheme="teal">
                Don't allow analytics
              </Radio>
            </Stack>
          </RadioGroup>
        </>
      ) : (
        <Text fontSize="sm">This hub doesn't collect usage analytics.</Text>
      )}
    </Container>
  )
}
export default Privacy
