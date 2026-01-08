#!/usr/bin/env python3
"""
Script to generate a large sample ASC file (5-20 MB) for testing CAN message visualization.

Usage:
    python generate_large_asc.py [output_file] [target_size_mb]

Examples:
    python generate_large_asc.py                          # Creates large_sample.asc (~10 MB)
    python generate_large_asc.py my_test.asc 5            # Creates my_test.asc (~5 MB)
    python generate_large_asc.py big_sample.asc 20        # Creates big_sample.asc (~20 MB)
"""

import random
import sys
import os
from datetime import datetime
from typing import TextIO


# CAN IDs to simulate - representing different ECUs/signals
CAN_IDS = [
    "100",  # Engine ECU
    "200",  # Transmission ECU
    "300",  # ABS/Brake ECU
    "400",  # Steering ECU
    "500",  # Body Control Module
    "600",  # Instrument Cluster
    "700",  # Climate Control
    "18FEF100",  # J1939 Engine Speed
    "18FF0021",  # J1939 Custom
    "0CF00400",  # J1939 Electronic Engine Controller
]

# Channels to use
CHANNELS = [1, 2]


def generate_random_data_bytes(dlc: int = 8) -> str:
    """Generate random hex data bytes for CAN message."""
    return " ".join(f"{random.randint(0, 255):02X}" for _ in range(dlc))


def generate_realistic_data_bytes(can_id: str, timestamp: float) -> str:
    """
    Generate somewhat realistic data patterns based on CAN ID.
    This creates more interesting visualizations with trends and patterns.
    """
    if can_id == "100":  # Engine RPM / Speed simulation
        # Simulate RPM changing over time (e.g., 800-6000 RPM)
        base_rpm = 800 + int(2000 * (1 + 0.5 * (1 + (timestamp % 60) / 30)))
        rpm_variation = random.randint(-50, 50)
        rpm = max(800, min(6500, base_rpm + rpm_variation))
        rpm_high = (rpm >> 8) & 0xFF
        rpm_low = rpm & 0xFF
        # Throttle position
        throttle = random.randint(0, 100)
        return (
            f"{rpm_low:02X} {rpm_high:02X} {throttle:02X} {random.randint(0, 255):02X} "
            f"{random.randint(0, 3):02X} 00 00 00"
        )

    elif can_id == "200":  # Vehicle speed simulation
        # Simulate speed changing with time (0-120 km/h cycle)
        speed = int(60 + 60 * abs((timestamp % 120) / 60 - 1))
        speed_variation = random.randint(-2, 2)
        speed = max(0, min(200, speed + speed_variation))
        speed_high = (speed * 100) >> 8
        speed_low = (speed * 100) & 0xFF
        gear = min(6, max(1, speed // 20))
        return f"{speed_low:02X} {speed_high:02X} 00 {gear:02X} 00 00 00 00"

    elif can_id == "300":  # Wheel speeds / ABS
        wheel_speed_base = int(50 + 50 * abs((timestamp % 120) / 60 - 1))
        fl = wheel_speed_base + random.randint(-2, 2)
        fr = wheel_speed_base + random.randint(-2, 2)
        rl = wheel_speed_base + random.randint(-2, 2)
        rr = wheel_speed_base + random.randint(-2, 2)
        return f"{fl:02X} {fr:02X} {rl:02X} {rr:02X} 00 00 00 00"

    elif can_id == "400":  # Steering angle
        # Simulate steering angle oscillating
        angle = int(180 + 90 * (timestamp % 10) / 5 - 90)
        angle_high = ((angle + 360) >> 8) & 0xFF
        angle_low = (angle + 360) & 0xFF
        return f"{angle_low:02X} {angle_high:02X} {random.randint(0, 100):02X} 00 00 00 00 00"

    elif can_id == "500":  # Body Control - doors, lights, etc.
        door_status = random.randint(0, 15)  # 4 doors: FL, FR, RL, RR
        lights = random.randint(0, 7)  # headlights, signals, etc.
        return f"{door_status:02X} {lights:02X} 00 00 00 00 00 00"

    elif can_id == "600":  # Instrument cluster - temperature, fuel, etc.
        coolant_temp = 85 + random.randint(-5, 15)  # Around 85-100°C
        fuel_level = random.randint(10, 100)
        battery_voltage = 12 + random.randint(0, 2)
        return (
            f"{coolant_temp:02X} {fuel_level:02X} {battery_voltage:02X} 00 00 00 00 00"
        )

    elif can_id == "700":  # Climate control
        target_temp = random.randint(18, 26)
        current_temp = target_temp + random.randint(-3, 3)
        fan_speed = random.randint(0, 7)
        ac_status = random.randint(0, 1)
        return f"{target_temp:02X} {current_temp:02X} {fan_speed:02X} {ac_status:02X} 00 00 00 00"

    else:  # J1939 or other extended IDs - more random data
        return generate_random_data_bytes(8)


def write_header(f: TextIO, start_date: datetime) -> None:
    """Write ASC file header."""
    date_str = start_date.strftime("%a %b %d %H:%M:%S.000 %Y")
    f.write(f"date {date_str}\n")
    f.write("base hex  timestamps absolute\n")
    f.write("internal events logged\n")
    f.write(f"Begin Triggerblock {date_str}\n")


def write_footer(f: TextIO) -> None:
    """Write ASC file footer."""
    f.write("End TriggerBlock\n")


def generate_asc_file(
    output_path: str,
    target_size_mb: float = 10.0,
    time_step_ms: float = 10.0,
    use_realistic_data: bool = True,
) -> None:
    """
    Generate a large ASC file with CAN messages.

    Args:
        output_path: Path to output ASC file
        target_size_mb: Target file size in megabytes (5-20 recommended)
        time_step_ms: Time step between messages in milliseconds
        use_realistic_data: If True, generate patterns; if False, random data
    """
    target_size_bytes = int(target_size_mb * 1024 * 1024)
    start_date = datetime.now()

    print(f"Generating ASC file: {output_path}")
    print(f"Target size: {target_size_mb:.1f} MB ({target_size_bytes:,} bytes)")
    print(f"Time step: {time_step_ms:.1f} ms")
    print(f"Data mode: {'Realistic patterns' if use_realistic_data else 'Random'}")
    print()

    timestamp = 0.0
    message_count = 0
    current_size = 0
    last_progress = 0

    with open(output_path, "w") as f:
        write_header(f, start_date)

        while current_size < target_size_bytes:
            # Select a random CAN ID and channel
            can_id = random.choice(CAN_IDS)
            channel = random.choice(CHANNELS)
            direction = random.choice(["Rx", "Tx"])
            dlc = 8  # Standard CAN has 8 bytes max

            # Generate data bytes
            if use_realistic_data:
                data_bytes = generate_realistic_data_bytes(can_id, timestamp)
            else:
                data_bytes = generate_random_data_bytes(dlc)

            # Format the CAN message line
            # Format: timestamp channel can_id direction d dlc data_bytes
            line = f"   {timestamp:.6f} {channel}  {can_id:<15} {direction}   d {dlc} {data_bytes}\n"
            f.write(line)

            message_count += 1
            current_size += len(line)
            timestamp += time_step_ms / 1000.0

            # Print progress every 10%
            progress = int((current_size / target_size_bytes) * 100)
            if progress >= last_progress + 10:
                last_progress = progress
                print(
                    f"Progress: {progress}% ({current_size / (1024 * 1024):.2f} MB, {message_count:,} messages)"
                )

        write_footer(f)

    # Get final file size
    final_size = os.path.getsize(output_path)
    duration_seconds = timestamp

    print()
    print("=" * 50)
    print("Generation Complete!")
    print("=" * 50)
    print(f"Output file: {output_path}")
    print(f"Final size: {final_size / (1024 * 1024):.2f} MB ({final_size:,} bytes)")
    print(f"Total messages: {message_count:,}")
    print(
        f"Simulated duration: {duration_seconds:.2f} seconds ({duration_seconds / 60:.2f} minutes)"
    )
    print(
        f"Average message rate: {message_count / duration_seconds:.1f} messages/second"
    )
    print(f"CAN IDs used: {len(CAN_IDS)}")


def main():
    """Main entry point."""
    # Default values
    output_file = "large_sample.asc"
    target_size_mb = 10.0

    # Parse command line arguments
    if len(sys.argv) >= 2:
        output_file = sys.argv[1]

    if len(sys.argv) >= 3:
        try:
            target_size_mb = float(sys.argv[2])
            if target_size_mb < 1 or target_size_mb > 100:
                print("Warning: Target size should be between 1-100 MB. Using 10 MB.")
                target_size_mb = 10.0
        except ValueError:
            print(f"Invalid size '{sys.argv[2]}'. Using default 10 MB.")
            target_size_mb = 10.0

    # Ensure output is in the samples directory if no path specified
    if not os.path.dirname(output_file):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_file = os.path.join(script_dir, output_file)

    generate_asc_file(output_file, target_size_mb)


if __name__ == "__main__":
    main()
