import {
  Container,
  Heading,
  Link,
  Radio,
  RadioGroup,
  Stack,
  Text,
} from "@chakra-ui/react"
import { useState } from "react"

import {
  type AnalyticsConsent,
  analyticsEnabled,
  getAnalyticsConsent,
  privacyPolicyUrl,
  setAnalyticsConsent,
} from "../../lib/analytics"

const Privacy = () => {
  const [consent, setConsent] = useState(getAnalyticsConsent)

  return (
    <Container maxW="full">
      <Heading size="sm" py={4}>
        Usage analytics
      </Heading>
      {analyticsEnabled ? (
        <>
          <Text fontSize="sm" mb={4}>
            Calkit can record which pages you visit and which features you use,
            so we can improve the features people rely on and remove the ones
            nobody does. It's never sold or used for advertising. This setting
            applies to this browser. See the{" "}
            <Link href={privacyPolicyUrl} isExternal textDecoration="underline">
              privacy policy
            </Link>{" "}
            for details.
          </Text>
          <RadioGroup
            value={consent ?? ""}
            onChange={(value) => {
              setAnalyticsConsent(value as AnalyticsConsent)
              setConsent(value as AnalyticsConsent)
            }}
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
