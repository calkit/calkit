import {
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Modal,
  ModalBody,
  ModalCloseButton,
  Input,
  Textarea,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"
import { useEffect } from "react"
import axios from "axios"
import mixpanel from "mixpanel-browser"

import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewStageProps {
  isOpen: boolean
  onClose: () => void
}

type OutputObject = {
  title: string
  description: string
}

type Stage = {
  template: "py-script" | "figure-from-excel" | "word-to-pdf" | null
  name: string
  cmd: string
  out: string
  deps: string | null // Comma-separated as input
  outputType: "figure" | "publication" | "dataset" | null
  outputObject: OutputObject | null
  inputFilePath: string | null
  excelChartIndex: number | null
  scriptPath: string | null
}

const NewStage = ({ isOpen, onClose }: NewStageProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    unregister,
    handleSubmit,
    reset,
    watch,
    getValues,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<Stage>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      excelChartIndex: 0,
      inputFilePath: "{CHANGE ME}",
      outputType: null,
      outputObject: null,
    },
  })
  const mutation = useMutation({
    mutationFn: (data: Stage) => {
      mixpanel.track("Clicked save new stage on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/pipeline/stages`
      let deps = null
      if (data.deps) {
        deps = data.deps.split(",")
      }
      let calkitType = null
      if (data.outputType) {
        calkitType = data.outputType
      }
      const postData = {
        name: data.name,
        cmd: data.cmd,
        deps: deps,
        outs: [data.out],
        calkit_type: calkitType,
        calkit_object: data.outputObject,
      }
      return axios.post(url, postData)
    },
    onSuccess: () => {
      showToast("Success!", "Stage added.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "pipeline"],
      })
    },
  })
  const onSubmit: SubmitHandler<Stage> = (data) => {
    mutation.mutate(data)
  }
  // Add a watcher for the "outputType" key so we can modify the form fields
  const watchOutputType = watch("outputType")
  const kindsWithTitle = ["publication", "figure", "dataset"]
  const watchTemplate = watch("template")
  // Update output artifact form fields based on type selected
  useEffect(() => {
    if (kindsWithTitle.includes(String(watchOutputType))) {
      register("outputObject.title")
    } else {
      unregister("outputObject.title")
    }
    if (watchOutputType) {
      register("outputObject.description")
    } else {
      unregister("outputObject.description")
    }
  }, [register, unregister, watchOutputType])
  // Update stage form fields based on template selected
  useEffect(() => {
    const template = String(watchTemplate)
    if (template === "py-script") {
      setValue("cmd", "calkit xenv -n {CHANGE ME} python {CHANGE ME}")
      setValue("outputType", null)
      register("scriptPath")
      unregister("inputFilePath")
      unregister("excelChartIndex")
    } else if (template === "figure-from-excel") {
      setValue(
        "cmd",
        "calkit office excel-chart-to-image {CHANGE ME} --sheet=1 --chart-index=0 {CHANGE ME}",
      )
      setValue("outputType", "figure")
      setValue("inputFilePath", "")
      register("excelChartIndex")
      register("inputFilePath")
      unregister("scriptPath")
    } else if (template === "word-to-pdf") {
      setValue(
        "cmd",
        "calkit office word-to-pdf {CHANGE ME}.docx --output {CHANGE ME}.pdf",
      )
      setValue("inputFilePath", "")
      setValue("outputType", null)
      register("inputFilePath")
      unregister("scriptPath")
      unregister("excelChartIndex")
    }
  }, [register, unregister, watchTemplate, setValue])
  // If script path changes, update command automatically
  const onScriptPathChange = (e: any) => {
    const scriptPath = String(e.target.value)
    setValue("cmd", `calkit xenv -n {CHANGE ME} python ${scriptPath}`)
    setValue("deps", scriptPath)
  }
  // If output path changes, update fields automatically
  const onOutputPathChange = (e: any) => {
    const outputPath = String(e.target.value)
    const formValues = getValues()
    if (watchTemplate === "figure-from-excel") {
      const inputPath = formValues.inputFilePath
      const idx = formValues.excelChartIndex
      const cmd = `calkit office excel-chart-to-image "${inputPath}" --sheet=1 --chart-index=${idx} "${outputPath}"`
      setValue("cmd", cmd)
    } else if (watchTemplate === "word-to-pdf") {
      const inputPath = formValues.inputFilePath
      const cmd = `calkit office word-to-pdf "${inputPath}" --output "${outputPath}"`
      setValue("cmd", cmd)
    }
  }
  // If Excel input file path changes, update fields accordingly
  const oninputFilePathChange = (e: any) => {
    const inputPath = String(e.target.value)
    const formValues = getValues()
    if (watchTemplate === "figure-from-excel") {
      const outputPath = formValues.out
      const idx = formValues.excelChartIndex
      const cmd = `calkit office excel-chart-to-image "${inputPath}" --chart-index=${idx} "${outputPath}"`
      setValue("cmd", cmd)
      setValue("deps", inputPath)
    }
  }
  // If Word doc input file path changes, update fields accordingly
  const onWordDocFilePathChange = (e: any) => {
    const inputPath = String(e.target.value)
    const formValues = getValues()
    if (watchTemplate === "word-to-pdf") {
      const outputPath = formValues.out
      const cmd = `calkit office word-to-pdf "${inputPath}" --output "${outputPath}"`
      setValue("cmd", cmd)
      setValue("deps", inputPath)
    }
  }
  // Function to return output path placeholder
  const getOutputPathPlaceholder = () => {
    if (watchTemplate === "word-to-pdf") {
      return "Ex: my-document.pdf"
    }
    return "Ex: figures/my-figure.png"
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>Add new pipeline stage</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isRequired isInvalid={!!errors.name} mb={2}>
              <FormLabel htmlFor="name">Name</FormLabel>
              <Input
                id="name"
                {...register("name", {})}
                placeholder="Ex: run-my-script"
              />
              {errors.name && (
                <FormErrorMessage>{errors.name.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mb={2}>
              <FormLabel htmlFor="template">Template</FormLabel>
              <Select
                id="template"
                placeholder="Select a template..."
                {...register("template", {})}
                defaultValue=""
              >
                <option value="">None</option>
                <option value="py-script">Run Python script</option>
                <option value="figure-from-excel">Figure from Excel</option>
                <option value="word-to-pdf">Word document to PDF</option>
              </Select>
            </FormControl>
            {/* Optional fields depending on template selected */}
            {watchTemplate === "py-script" ? (
              <FormControl isRequired isInvalid={!!errors.scriptPath} mb={2}>
                <FormLabel htmlFor="script-path">Script path</FormLabel>
                <Input
                  id="scriptPath"
                  {...register("scriptPath", {})}
                  placeholder="Ex: scripts/my-script.py"
                  onChange={onScriptPathChange}
                />
              </FormControl>
            ) : (
              ""
            )}
            {watchTemplate === "figure-from-excel" ? (
              <FormControl isRequired isInvalid={!!errors.inputFilePath} mb={2}>
                <FormLabel htmlFor="inputFilePath">Excel file path</FormLabel>
                <Input
                  id="inputFilePath"
                  {...register("inputFilePath", {})}
                  placeholder="Ex: my-excel-file.xlsx"
                  onChange={oninputFilePathChange}
                />
              </FormControl>
            ) : (
              ""
            )}
            {watchTemplate === "word-to-pdf" ? (
              <FormControl isRequired isInvalid={!!errors.inputFilePath} mb={2}>
                <FormLabel htmlFor="inputFilePath">
                  Word document file path
                </FormLabel>
                <Input
                  id="inputFilePath"
                  {...register("inputFilePath", {})}
                  placeholder="Ex: my-document.docx"
                  onChange={onWordDocFilePathChange}
                />
              </FormControl>
            ) : (
              ""
            )}
            {/* Output path optional field */}
            <FormControl isRequired isInvalid={!!errors.out} mb={2}>
              <FormLabel htmlFor="out">Output path</FormLabel>
              <Input
                id="out"
                {...register("out", {})}
                placeholder={getOutputPathPlaceholder()}
                onChange={onOutputPathChange}
              />
              {errors.out && (
                <FormErrorMessage>{errors.out.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl isRequired isInvalid={!!errors.cmd} mb={2}>
              <FormLabel htmlFor="cmd">Command</FormLabel>
              <Input
                id="cmd"
                {...register("cmd", {})}
                placeholder="Ex: calkit xenv -n main python scripts/my-script.py"
              />
              {errors.cmd && (
                <FormErrorMessage>{errors.cmd.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mb={2}>
              <FormLabel htmlFor="deps">
                Input dependencies (comma-separated paths)
              </FormLabel>
              <Input
                id="deps"
                {...register("deps", {})}
                placeholder="Ex: scripts/my-script.py,data/my-data.csv"
              />
              {errors.deps && (
                <FormErrorMessage>{errors.deps.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Output artifact type */}
            <FormControl isRequired isInvalid={!!errors.outputType} mb={2}>
              <FormLabel htmlFor="outputType">Output artifact type</FormLabel>
              <Select
                id="outputType"
                {...register("outputType", {})}
                placeholder="Select a type..."
              >
                <option value="">None</option>
                <option value="figure">Figure</option>
                <option value="dataset">Dataset</option>
                <option value="publication">Publication</option>
              </Select>
              {errors.outputType && (
                <FormErrorMessage>{errors.outputType.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Add other properties depending on artifact type */}
            {kindsWithTitle.includes(String(watchOutputType)) ? (
              <FormControl
                isRequired
                isInvalid={!!errors.outputObject?.title}
                mb={2}
              >
                <FormLabel htmlFor="outputObject.title">Title</FormLabel>
                <Input
                  id="outputObject.title"
                  {...register("outputObject.title", {})}
                  placeholder="Enter title..."
                />
              </FormControl>
            ) : (
              ""
            )}
            {watchOutputType ? (
              <FormControl
                mb={2}
                isRequired
                isInvalid={!!errors.outputObject?.description}
              >
                <FormLabel htmlFor="outputObject.description">
                  Description
                </FormLabel>
                <Textarea
                  id="outputObject.description"
                  {...register("outputObject.description", {})}
                  placeholder="Enter description..."
                />
              </FormControl>
            ) : (
              ""
            )}
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting || mutation.isPending}
            >
              Save
            </Button>
            <Button onClick={onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}

export default NewStage
