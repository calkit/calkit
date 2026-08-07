import { useRef } from "react"
import {
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
  type InputProps,
} from "@chakra-ui/react"
import { CloseIcon } from "@chakra-ui/icons"

interface ClearableInputProps extends InputProps {
  value: string
  onValueChange: (value: string) => void
}

export default function ClearableInput({
  value,
  onValueChange,
  ...rest
}: ClearableInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const { size, width, maxW, minW, w, flex, ...inputRest } = rest
  return (
    <InputGroup
      {...(size ? { size } : {})}
      {...(width !== undefined ? { width } : {})}
      {...(maxW !== undefined ? { maxW } : {})}
      {...(minW !== undefined ? { minW } : {})}
      {...(w !== undefined ? { w } : {})}
      {...(flex !== undefined ? { flex } : {})}
    >
      <Input
        {...inputRest}
        ref={inputRef}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            onValueChange("")
            inputRef.current?.blur()
          }
          inputRest.onKeyDown?.(e)
        }}
      />
      {value && (
        <InputRightElement>
          <IconButton
            aria-label="Clear"
            icon={<CloseIcon boxSize="8px" />}
            size="xs"
            variant="ghost"
            onClick={() => onValueChange("")}
          />
        </InputRightElement>
      )}
    </InputGroup>
  )
}
