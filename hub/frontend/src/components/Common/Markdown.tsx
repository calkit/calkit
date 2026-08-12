import {
  Code,
  Heading,
  Link,
  ListItem,
  OrderedList,
  Text,
  UnorderedList,
  useColorModeValue,
} from "@chakra-ui/react"
import { Box } from "@chakra-ui/react"
import React from "react"
import ReactMarkdown from "react-markdown"
import rehypeKatex from "rehype-katex"
import rehypeRaw from "rehype-raw"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import "katex/dist/katex.min.css"

// Preserve the class names remark-math emits (`math`, `math-inline`,
// `math-display`) through sanitization so rehype-katex, which runs afterward,
// can find and render them. KaTeX's own output is trusted (no user scripts).
const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    span: [...(defaultSchema.attributes?.span ?? []), "className"],
    div: [...(defaultSchema.attributes?.div ?? []), "className"],
  },
}

interface MarkdownProps {
  children: string
  /** Render user-controlled short text without block elements or links. */
  inline?: boolean
}

interface codeProps extends React.HTMLAttributes<HTMLElement> {
  insidePre?: boolean
}

const H1 = (props: any) => {
  return <Heading size="lg" mb={4} {...props} />
}
const H2 = (props: any) => {
  return <Heading size="md" mb={2} mt={3} {...props} />
}
const H3 = (props: any) => {
  return <Heading size="sm" my={2} {...props} />
}
const p = (props: any) => {
  return <Text my={2} mt={3} {...props} />
}
const BlueLink = (props: any) => {
  return <Link variant="blue" {...props} />
}

// Send prop to children of <pre> to differentiate if they are block code or not
const pre = ({ children, ...props }: any) => {
  return (
    <pre {...props}>
      {React.Children.map(children, (child) => {
        return React.cloneElement(child, { insidePre: true })
      })}
    </pre>
  )
}

const code = ({ insidePre = false, ...props }: codeProps) => {
  if (insidePre) {
    return <Code my={2} whiteSpace={"pre"} display={"block"} p={2} {...props} />
  }
  return <Code my={0} whiteSpace={"pre"} px={1} {...props} />
}

const Markdown = ({ children, inline = false }: MarkdownProps) => {
  const tableBorderColor = useColorModeValue("gray.200", "whiteAlpha.300")
  const tableHeaderBg = useColorModeValue("gray.50", "whiteAlpha.100")
  const tableHeaderText = useColorModeValue("gray.700", "gray.100")
  const tableRowAltBg = useColorModeValue("blackAlpha.50", "whiteAlpha.50")

  const table = ({ children, ...props }: any) => {
    return (
      <Box
        my={4}
        overflowX="auto"
        borderWidth="1px"
        borderColor={tableBorderColor}
        borderRadius="md"
      >
        <Box
          as="table"
          width="full"
          borderCollapse="separate"
          borderSpacing={0}
          {...props}
        >
          {children}
        </Box>
      </Box>
    )
  }

  const tr = ({ ...props }: any) => {
    return <Box as="tr" _even={{ bg: tableRowAltBg }} {...props} />
  }

  const th = ({ ...props }: any) => {
    return (
      <Box
        as="th"
        px={3}
        py={2}
        textAlign="left"
        fontWeight="semibold"
        bg={tableHeaderBg}
        color={tableHeaderText}
        borderBottomWidth="1px"
        borderColor={tableBorderColor}
        whiteSpace="normal"
        {...props}
      />
    )
  }

  const td = ({ ...props }: any) => {
    return (
      <Box
        as="td"
        px={3}
        py={2}
        borderBottomWidth="1px"
        borderColor={tableBorderColor}
        verticalAlign="top"
        whiteSpace="normal"
        {...props}
      />
    )
  }

  const inlineParagraph = ({ children, ...props }: any) => {
    return (
      <Text as="span" my={0} {...props}>
        {children}
      </Text>
    )
  }

  const components = {
    h1: H1,
    h2: H2,
    h3: H3,
    li: ListItem,
    ol: OrderedList,
    ul: UnorderedList,
    p: inline ? inlineParagraph : p,
    pre,
    code,
    a: BlueLink,
    table,
    tr,
    th,
    td,
  }

  return (
    <Box
      /*
       * Chakra's CSS reset sets img { display: block }, which makes README badges
       * stack vertically. Override within markdown so images (and linked images)
       * behave inline like on GitHub.
       */
      sx={{
        "& p img": {
          display: "inline",
          verticalAlign: "middle",
          marginRight: "0.375rem",
        },
        "& p a img": {
          display: "inline",
          verticalAlign: "middle",
          marginRight: "0.375rem",
        },
        // Avoid extra right margin on the last image in a paragraph
        "& p img:last-child, & p a:last-child img": {
          marginRight: 0,
        },
      }}
    >
      <ReactMarkdown
        components={components}
        allowedElements={
          inline
            ? ["p", "span", "em", "strong", "del", "code", "br"]
            : undefined
        }
        unwrapDisallowed={inline}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          rehypeRaw,
          [rehypeSanitize, sanitizeSchema],
          rehypeKatex,
        ]}
      >
        {children}
      </ReactMarkdown>
    </Box>
  )
}

export default Markdown
