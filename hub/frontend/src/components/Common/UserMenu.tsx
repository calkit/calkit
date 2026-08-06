import {
  Box,
  IconButton,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
} from "@chakra-ui/react"
import { Link } from "@tanstack/react-router"
import { GiFox } from "react-icons/gi"
import { FiLogOut, FiUser, FiUsers } from "react-icons/fi"
import { useQueryClient } from "@tanstack/react-query"

import { type UserPublic } from "../../client"
import useAuth from "../../hooks/useAuth"

const UserMenu = () => {
  const { logout } = useAuth()
  const queryClient = useQueryClient()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])

  const handleLogout = async () => {
    logout()
  }

  return (
    <>
      {/* Desktop */}
      <Box
        display={{ base: "none", md: "block" }}
        alignContent="center"
        right={4}
      >
        <Menu>
          <MenuButton
            as={IconButton}
            aria-label="Options"
            icon={<GiFox color="white" fontSize="18px" />}
            bg="ui.main"
            isRound
            data-testid="user-menu"
          />
          <MenuList>
            {currentUser?.is_superuser && (
              <MenuItem
                icon={<FiUsers fontSize="18px" />}
                as={Link}
                to="/admin"
              >
                Admin
              </MenuItem>
            )}
            <MenuItem
              icon={<FiUser fontSize="18px" />}
              as={Link}
              to="/settings"
            >
              Settings
            </MenuItem>
            <MenuItem
              icon={<FiLogOut fontSize="18px" />}
              onClick={handleLogout}
              color="ui.danger"
              fontWeight="bold"
            >
              Log out
            </MenuItem>
          </MenuList>
        </Menu>
      </Box>
    </>
  )
}

export default UserMenu
