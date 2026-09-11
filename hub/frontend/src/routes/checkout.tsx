import { Container, Box, useColorModeValue } from "@chakra-ui/react"
import { createFileRoute, redirect } from "@tanstack/react-router"
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout,
} from "@stripe/react-stripe-js"
import { loadStripe } from "@stripe/stripe-js"
import { z } from "zod"

const checkoutSearchSchema = z.object({
  client_secret: z.string(),
})

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY)

export const Route = createFileRoute("/checkout")({
  component: Checkout,
  validateSearch: (search) => checkoutSearchSchema.parse(search),
  onError: () => {
    throw redirect({ to: "/" })
  },
})

function Checkout() {
  const color = useColorModeValue("ui.main", "ui.main")
  const params = Route.useSearch()
  const options = { clientSecret: params.client_secret }

  return (
    <Container
      alignContent="center"
      justifyContent="center"
      id="checkout"
      borderRadius={"lg"}
      width={"100vw"}
      height={"100vh"}
    >
      <Box p="30px" borderColor={color} borderRadius={"xl"} borderWidth={3}>
        <EmbeddedCheckoutProvider stripe={stripePromise} options={options}>
          <EmbeddedCheckout />
        </EmbeddedCheckoutProvider>
      </Box>
    </Container>
  )
}
