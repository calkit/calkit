import {
  Box,
  IconButton,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverHeader,
  PopoverTrigger,
  Text,
  VStack,
  Button,
  Flex,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { FaBell } from "react-icons/fa"

import { MiscService } from "../../client"

export default function NotificationBell() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.50", "gray.700")

  const notificationsQuery = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => MiscService.getNotifications({ unreadOnly: true }),
    refetchInterval: 60_000,
  })

  const markReadMutation = useMutation({
    mutationFn: (id: string) =>
      MiscService.markNotificationRead({ notificationId: id }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
    },
  })

  const markAllReadMutation = useMutation({
    mutationFn: () => MiscService.markAllNotificationsRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
    },
  })

  const notifications = notificationsQuery.data ?? []
  const unreadCount = notifications.length

  const handleClick = (id: string, link: string) => {
    markReadMutation.mutate(id)
    navigate({ to: link as any })
  }

  return (
    <Popover placement="bottom-end">
      <PopoverTrigger>
        <Box position="relative" display="inline-block">
          <IconButton
            aria-label="Notifications"
            icon={<FaBell />}
            variant="ghost"
            size="sm"
          />
          {unreadCount > 0 && (
            <Box
              position="absolute"
              top="-2px"
              right="-2px"
              bg="red.500"
              color="white"
              borderRadius="full"
              fontSize="9px"
              fontWeight="bold"
              minW="16px"
              h="16px"
              display="flex"
              alignItems="center"
              justifyContent="center"
              px="3px"
              pointerEvents="none"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </Box>
          )}
        </Box>
      </PopoverTrigger>
      <PopoverContent w="320px">
        <PopoverArrow />
        <PopoverCloseButton />
        <PopoverHeader>
          <Flex align="center" justify="space-between" pr={6}>
            <Text fontWeight="semibold" fontSize="sm">
              Notifications
            </Text>
            {unreadCount > 0 && (
              <Button
                size="xs"
                variant="ghost"
                onClick={() => markAllReadMutation.mutate()}
                isLoading={markAllReadMutation.isPending}
              >
                Mark all read
              </Button>
            )}
          </Flex>
        </PopoverHeader>
        <PopoverBody px={2} py={2} maxH="400px" overflowY="auto">
          {notifications.length === 0 ? (
            <Text fontSize="sm" color="gray.500" px={2} py={1}>
              No new notifications
            </Text>
          ) : (
            <VStack align="stretch" spacing={1}>
              {notifications.map((n) => (
                <Box
                  key={n.id}
                  px={3}
                  py={2}
                  borderRadius="md"
                  borderWidth={1}
                  borderColor={borderColor}
                  cursor="pointer"
                  _hover={{ bg: hoverBg }}
                  onClick={() => handleClick(n.id!, n.link)}
                >
                  <Text fontSize="sm">{n.message}</Text>
                  <Text fontSize="xs" color="gray.500" mt={0.5}>
                    {n.created ? new Date(n.created).toLocaleDateString() : ""}
                  </Text>
                </Box>
              ))}
            </VStack>
          )}
        </PopoverBody>
      </PopoverContent>
    </Popover>
  )
}
