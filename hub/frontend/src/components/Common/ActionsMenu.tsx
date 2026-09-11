import {
  Button,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  useDisclosure,
} from "@chakra-ui/react"
import { BsThreeDotsVertical } from "react-icons/bs"
import { FiEdit, FiTrash } from "react-icons/fi"

import type { UserPublic, ProjectPublic } from "../../client"
import EditUser from "../Admin/EditUser"
import EditProject from "../Projects/EditProject"
import Delete from "./DeleteAlert"

interface ActionsMenuProps {
  type: string
  value: UserPublic | ProjectPublic
  disabled?: boolean
}

const ActionsMenu = ({ type, value, disabled }: ActionsMenuProps) => {
  const editEntityModal = useDisclosure()
  const deleteModal = useDisclosure()

  return (
    <>
      <Menu>
        <MenuButton
          isDisabled={disabled}
          as={Button}
          rightIcon={<BsThreeDotsVertical />}
          variant="unstyled"
        />
        <MenuList>
          <MenuItem
            onClick={editEntityModal.onOpen}
            icon={<FiEdit fontSize="16px" />}
          >
            Edit {type.toLowerCase()}
          </MenuItem>
          <MenuItem
            onClick={deleteModal.onOpen}
            icon={<FiTrash fontSize="16px" />}
            color="ui.danger"
          >
            Delete {type.toLowerCase()}
          </MenuItem>
        </MenuList>
        {type === "User" ? (
          <EditUser
            user={value as UserPublic}
            isOpen={editEntityModal.isOpen}
            onClose={editEntityModal.onClose}
          />
        ) : (
          <EditProject
            project={value as ProjectPublic}
            isOpen={editEntityModal.isOpen}
            onClose={editEntityModal.onClose}
          />
        )}
        <Delete
          type={type}
          id={value.id}
          isOpen={deleteModal.isOpen}
          onClose={deleteModal.onClose}
        />
      </Menu>
    </>
  )
}

export default ActionsMenu
