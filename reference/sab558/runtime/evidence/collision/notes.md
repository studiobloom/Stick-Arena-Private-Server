# Scenario: collision (1 client)

Left held 4 s, then right held 4 s. A wall contact should show the client's own
velocity reversing (`jhzeUQ` does `xVel *= -0.5`), which is visible as a sign
change in consecutive `1` packets.
