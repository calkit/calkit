# Calkit VS Code extension

In this VS Code extension we want to be able to support this flow:

1. Open notebook
2. Click "select kernel"
3. Click "Calkit environments..."
4. Create new Calkit environment: kind is SLURM --> enter name, host, default options like `--gpus`, `--time`.
5. Create new Calkit environment: kind is Julia --> enter name, path to Project.toml, Julia version prefilled with currently detected Julia
6. Go back to Calkit environments list and select nested slurm:julia environment with slurm options prefilled from defaults
7. Do some work
8. Click a stop button in the notebook toolbar to stop the srun job and free up the resources
9. Go away and close VS Code
10. Return and open the notebook, kernel is selected, but push a button in the notebook toolbar to start the slurm job for the kernel and connect to that
