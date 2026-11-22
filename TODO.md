# Firmware TODO

Requirements for the Christmas tree board firmware, gathered on 2026-11-22.
No firmware exists yet: there is no source directory, toolchain or build setup in this repo.

Items are marked **Decided** (agreed with the owner), **Proposed** (suggested, not yet agreed) or **Unverified** (needs checking on hardware or against the datasheet). Do not treat Proposed items as requirements without asking.

## Goal

Drive six LEDs with PWM-controlled brightness to show animated patterns, on a CR2032 coin cell, with the lowest practical power consumption.

## Hardware summary

Source of truth is `tree.kicad_sch`. The PCB (`tree.kicad_pcb`) is not routed yet and has not been updated with the latest schematic changes.

- **MCU:** Puya PY32F002BF15U6 (Cortex-M0+, 24 KB flash, 3 KB RAM, QFN-20).
  Datasheet: https://download.py32.org/Datasheet/en/PY32F002B_Datasheet_V1.8.pdf
- **Supply:** CR2032 through slide switch SW1 to VCC. 100 nF decoupling (C1). No regulator.
- **LEDs:** active low. Anode to VCC through 1.2 kΩ, cathode to the MCU pin. The pin sinks current, so PWM output polarity must be inverted (pin low = LED on).
  - D1: orange, CT-1608UOC-P6-0H, top of the tree (the "star")
  - D2-D6: red, CT-1608URC-P6-0H
- **Programming:** SWD on J1: 1 GND, 2 VCC, 3 SWDIO, 4 SWCLK, 5 NRST.
- **No button** is fitted. The only user control is the slide switch.

### Pin map

| LED | Position | Pin | Timer channel | AF |
|---|---|---|---|---|
| D1 | Star, top | PA5 (18) | TIM14 CH1 | AF5 |
| D2 | Upper left | PA0 (13) | TIM1 CH1 | AF2 |
| D3 | Upper right | PA1 (14) | TIM1 CH2 | AF2 |
| D4 | Lower left | PB1 (11) | TIM1 CH4 | AF3 |
| D5 | Lower right | PA7 (20) | TIM1 CH4 | AF2 |
| D6 | Centre | PB2 (10) | TIM1 CH3 | AF3 |

Other pins:

- SWCLK = PA2 (15), SWDIO = PB6 (5), NRST = PC0 (1). Keep these working.
- Unused, no-connect: PA3, PA4, PA6, PB0, PB3, PB4, PB5, PB7, PC1. Leave in analog mode (the reset default).

**Unverified:** the AF numbers were read from a garbled text extraction of the datasheet's alternate-function tables. Confirm each against the datasheet or the vendor headers before relying on them.

## Requirements

### PWM and LED groups

- **Decided:** use hardware timer PWM, not software PWM.
- **Decided:** four brightness groups: D1 alone, D2+D3, D4+D5, D6 alone.
- D4 and D5 share TIM1 CH4 in hardware, so they are always identical.
- D2 and D3 are on separate channels (CH1, CH2). Write the same duty to both by default. They can be driven differently later if wanted.
- **Unverified:** routing one timer channel to two pins at once (PA7 and PB1 both on TIM1 CH4). This is expected to work on this GPIO architecture but is not stated in the datasheet. Test on the prototype.
- **Proposed:** 8-bit resolution at about 128 Hz (timer clocked at 32.768 kHz, period 256 counts). TIM1 and TIM14 should use the same period.
- **Proposed:** pass brightness through a gamma lookup table so fades look even. About 25% duty looks half-bright.
- **Proposed:** offset the on-times of different channels within the period (for example, mixing PWM mode 1 and mode 2) so all LEDs do not switch on at the same instant. This reduces peak current on an aged cell.

### Power

- **Decided:** minimising power consumption is the main design goal.
- **Proposed:** run the system clock from the internal 32.768 kHz oscillator (LSI) while a pattern plays, and sit in Sleep mode between animation updates, with flash sleep enabled. Datasheet typical for this state is about 85 µA.
- **Proposed:** keep the animation update cheap: integer maths and lookup tables, a few tens of updates per second. At 32.768 kHz the CPU has only about 32,000 cycles per second in total.
- **Proposed:** when nothing is displayed, enter Stop mode with the low-power regulator selected. Datasheet typical is 1.5 µA; with the main regulator it is 75 µA, so the regulator setting matters.
- **Proposed:** brown-out reset off or at its lowest level. The LEDs fade out near 2 V anyway; the MCU runs down to 1.7 V.
- **Proposed:** auto-off after a few hours of running (enter Stop until the slide switch is cycled), in case it is left on.
- **Proposed:** stay on the fast oscillator for one to two seconds after reset before dropping to low-power clocking, so a debug probe can connect and reflash. Connecting under reset via NRST is the fallback.

### Patterns

The pattern set is **not decided**. Candidates, with estimated average duty per LED:

| Pattern | Description | Avg. duty per LED |
|---|---|---|
| Star heartbeat | Only D1 pulses slowly | 30% on D1 only |
| Twinkle | Groups flash briefly at random, mostly dark | 10% |
| Cascade | Light runs star, upper, centre, lower, with fades | 15% |
| Breathing | All fade up and down together | 31% at full peak |
| Steady glow | All on at half perceived brightness | 25% |

- **Proposed:** cap peak duty (for example at 50%) to save power and to leave headroom for voltage compensation.
- **Open:** how patterns are selected. There is no button. Options are a single fixed pattern, cycling on a timer, or advancing on each power-up (would need a value stored in flash). Adding a button was discussed but is not in the schematic.

### Cell voltage compensation

Discussed as possible; **not decided** whether to implement.

- No hardware change is needed: the reference is an internal ADC channel and VCC is the ADC's own reference, so no pin, divider or extra part is involved.
- Measure VCC by reading the internal 1.2 V reference (VREFINT, 1.17-1.23 V) with the ADC, using VCC as the ADC reference: `VCC = 1.2 V * 4095 / reading`.
- Sample every few seconds, at a consistent moment with the LEDs off.
- Scale duty by `(2.9 - 1.8) / (VCC - 1.8)` using a lookup table. Cap the correction at about 2x and let brightness fade below that.
- **Unverified:** the datasheet specifies the ADC only at 6 and 12 MHz clocks. A measurement may need a brief switch to the fast oscillator.
- **Proposed:** use the same measurement to switch to a low-power pattern or a "battery low" indication near end of life.

## Reference figures

Calculated from datasheets and a simple discharge model, not measured.

- LED current with 1.2 kΩ: about 1.0 mA per LED on a fresh 3.0 V cell, about 0.8 mA at 2.8 V.
- LED forward voltage near 1 mA: about 1.8 V.
- Average draw is roughly `0.085 mA + (LED current) * (sum of the six duty cycles)`.
- Estimated on-time above half brightness: about 340 h for Twinkle, 240 h for Cascade, 150 h for Steady glow, 125 h for Breathing (roughly +/-30%).
- MCU absolute limits: 20 mA per pin, 80 mA total.

## Open hardware questions that affect firmware

- **Resistor values.** R1-R6 are 1.2 kΩ. The P6-0H LEDs are about three times brighter per mA than the original reds, so raising R2-R6 to about 3.3-3.9 kΩ was suggested to cut current to a third. To be chosen by eye on the prototype. D1 and the reds are now about equally bright at the same current.
- **Button.** Not fitted. Nine GPIOs are free if one is added (button to ground, internal pull-up, wake from Stop by pin interrupt).

## First steps for whoever picks this up

1. Ask the owner which patterns they want and how patterns are selected.
2. Choose a toolchain and project layout. None has been chosen. Common options for this MCU family are GCC with the vendor HAL/LL libraries, flashed over SWD.
3. Bring-up test: all six LEDs on hardware PWM at a fixed duty, confirming the pin map, AF numbers, inverted polarity and the shared CH4 output.
4. Move the clock to LSI, confirm 128 Hz PWM without flicker, and measure Sleep current.
5. Implement patterns, then measure the average current of each and compare with the estimates above.
