# Reproducibility

Reproducibility is commonly defined as:

> Given the inputs and process definitions, it's possible to reproduce the
> same outputs.

A more measurable definition would be:

> Reproducibility is measured by the time it takes to verify the outputs
> truly reflect the inputs and process definitions.

What do we mean by inputs?

Inputs are essentially primary artifacts--ones created from nothing or
acquired from elsewhere.
Examples include:

- Raw data files
- Source code
- Configuration files
- Text files, e.g., for a manuscript
- Diagrams created by drawing
- Computational environment specifications

The main output of a research project is the article itself,
which is typically in PDF form.
This output is typically composed of the text input and some intermediate
outputs like figures, tables, and numerical results.

So, to verify the output truly reflects the inputs and process definitions,
we need to be able to trace through the entire path.
We need to know the exact _provenance_.

Process definitions describe how to turn the inputs into the outputs.
For example,

> Run the script with these arguments.

> Create the computational environment from the requirements.txt file.

Let's go through some example studies and measure reproducibility.

This paper does not provide any of its inputs.
We only have a single output, the PDF,
and the process definitions are described in prose,
which is fairly imprecise.

To test its reproducibility, we will therefore need to recreate
the inputs from how they are described in the paper.
We will need to either carry out the processes manually or write
our own new computations to execute.

In short, this way of doing research is highly irreproducible,
since it would take a very long time to verify.

On the other hand,
what if we just trust the authors?
Can we call the study reproducible if everything sounds logical and plausible?
This is of course subjective,
but we believe prose descriptions of how the inputs were generated and
processed are insufficient.
