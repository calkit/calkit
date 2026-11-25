# Simulate a damped oscillator, x'' + 2 zeta omega x' + omega^2 x = 0, with
# fourth-order Runge-Kutta
using DelimitedFiles
using JSON

zeta, omega = 0.05, 2pi
dt, n_steps = 0.01, 2000
accel(x, v) = -2 * zeta * omega * v - omega^2 * x
states = zeros(n_steps + 1, 3)
x, v = 1.0, 0.0
for i in 0:n_steps
    states[i+1, :] = [round(i * dt; digits=4), x, v]
    k1x, k1v = v, accel(x, v)
    k2x, k2v = v + dt / 2 * k1v, accel(x + dt / 2 * k1x, v + dt / 2 * k1v)
    k3x, k3v = v + dt / 2 * k2v, accel(x + dt / 2 * k2x, v + dt / 2 * k2v)
    k4x, k4v = v + dt * k3v, accel(x + dt * k3x, v + dt * k3v)
    global x += dt / 6 * (k1x + 2k2x + 2k3x + k4x)
    global v += dt / 6 * (k1v + 2k2v + 2k3v + k4v)
end
mkpath("data")
mkpath("results")
open("data/sim.csv", "w") do f
    writedlm(f, [["t" "x" "v"]; states], ',')
end
open("results/sim.json", "w") do f
    JSON.print(
        f, Dict("zeta" => zeta, "omega" => omega, "dt" => dt, "n_steps" => n_steps), 2
    )
end
