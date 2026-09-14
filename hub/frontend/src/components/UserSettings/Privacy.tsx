import {
  Container,
  Heading,
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
            Calkit can use Mixpanel to learn how the hub is used: the pages you
            visit and features you use, along with your browser, device, and
            approximate location, linked to your account. This setting applies
            to this browser.
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
