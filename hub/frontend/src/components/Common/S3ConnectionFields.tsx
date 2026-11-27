// Form fields for keys to S3 or S3-compatible storage, e.g., OSN

import {
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Input,
} from "@chakra-ui/react"
import type { FieldErrors, UseFormRegister } from "react-hook-form"

import { maskedText, noAutofill } from "../../lib/autofill"

export interface S3ConnectionForm {
  name: string
  endpoint_url: string
  region: string
  access_key_id: string
  secret_access_key: string
}

export const emptyS3Connection: S3ConnectionForm = {
  name: "",
  endpoint_url: "",
  region: "",
  access_key_id: "",
  secret_access_key: "",
}

interface S3ConnectionFieldsProps<T extends S3ConnectionForm> {
  register: UseFormRegister<T>
  errors: FieldErrors<T>
  // The name can't change once saved
  nameReadOnly?: boolean
}

function S3ConnectionFields<T extends S3ConnectionForm>({
  register,
  errors,
  nameReadOnly,
}: S3ConnectionFieldsProps<T>) {
  // The fields are the same in any form holding them
  const reg = register as unknown as UseFormRegister<S3ConnectionForm>
  const errs = errors as FieldErrors<S3ConnectionForm>
  return (
    <>
      <FormControl isInvalid={!!errs.name}>
        <FormLabel htmlFor="s3-name">Connection name</FormLabel>
        <Input
          id="s3-name"
          placeholder="osn"
          isReadOnly={nameReadOnly}
          {...noAutofill}
          {...reg("name", {
            required: "Name required",
            pattern: {
              value: /^[a-z0-9][a-z0-9-]{1,63}$/,
              message: "Use lowercase letters, numbers, and dashes",
            },
          })}
        />
        {errs.name && <FormErrorMessage>{errs.name.message}</FormErrorMessage>}
      </FormControl>
      <FormControl mt={4} isInvalid={!!errs.endpoint_url}>
        <FormLabel htmlFor="s3-endpoint">Endpoint</FormLabel>
        <Input
          id="s3-endpoint"
          placeholder="https://mghp.osn.xsede.org"
          {...noAutofill}
          {...reg("endpoint_url", {
            pattern: {
              value: /^https?:\/\/[^/\s]+\/?$/,
              message: "Use a URL like https://host",
            },
          })}
        />
        <FormHelperText>Blank for AWS</FormHelperText>
        {errs.endpoint_url && (
          <FormErrorMessage>{errs.endpoint_url.message}</FormErrorMessage>
        )}
      </FormControl>
      <FormControl mt={4}>
        {/* Split so Dashlane doesn't take it for an address */}
        <FormLabel htmlFor="s3-region">Regi{"\u200b"}on</FormLabel>
        <Input
          id="s3-region"
          placeholder="Optional"
          {...noAutofill}
          {...reg("region")}
        />
      </FormControl>
      <FormControl mt={4} isInvalid={!!errs.access_key_id}>
        <FormLabel htmlFor="s3-key-id">Access key</FormLabel>
        <Input
          id="s3-key-id"
          {...noAutofill}
          {...reg("access_key_id", { required: "Access key ID required" })}
        />
        {errs.access_key_id && (
          <FormErrorMessage>{errs.access_key_id.message}</FormErrorMessage>
        )}
      </FormControl>
      <FormControl mt={4} isInvalid={!!errs.secret_access_key}>
        <FormLabel htmlFor="s3-secret">Secret access key</FormLabel>
        <Input
          id="s3-secret"
          sx={maskedText}
          {...noAutofill}
          {...reg("secret_access_key", {
            required: "Secret access key required",
          })}
        />
        <FormHelperText>Read-only keys work for reading files</FormHelperText>
        {errs.secret_access_key && (
          <FormErrorMessage>{errs.secret_access_key.message}</FormErrorMessage>
        )}
      </FormControl>
    </>
  )
}

export default S3ConnectionFields
