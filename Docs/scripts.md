# Scripts Plan for Viral Video Recreation Tool

## Purpose

This document defines the individual scripts needed to build the Viral Video Recreation Tool described in `product-requirements.md`.

The goal is to keep each part of the pipeline isolated into small Python scripts that can work together through shared files and structured JSON outputs.

## Current Direction

The preferred workflow in this branch is script-based boundary detection.

The app should:

1. ingest the full source video
2. detect clip boundaries locally using FFmpeg scene-change analysis
3. extract the first frame of each detected clip
4. output a compact JSON file with clip start, end, and duration

This branch is focused on clip boundary timing and clip-start images only. It does not rely on Gemini for clip timing.

## Recommended Approach

Each script should do one job only.

Scripts should communicate through:

- a shared `run_id`
- folders created for each run
- JSON metadata files
- image and video files stored in predictable paths

This keeps the system modular, debuggable, and easy to rerun from any failed step.

## Suggested Folder Structure

```text
project/
  Docs/
    product-requirements.md
    scripts.md
  scripts/
    run_pipeline.py
    setup_run.py
    ingest_video.py
    detect_scenes.py
    split_clips.py
    analyze_clip.py
    analyze_all_clips.py
    extract_first_frame.py
    extract_all_first_frames.py
    generate_frame_prompt.py
    modify_frame_with_chatgpt.py
    modify_all_frames.py
    create_animation_prompt.py
    animate_clip.py
    animate_all_clips.py
    poll_animation_jobs.py
    merge_clips.py
    copy_or_rebuild_audio.py
    assemble_final_video.py
    validate_run.py
    cleanup_temp_files.py
  data/
    runs/
      <run_id>/
        input/
        clips/
        frames/
        modified_frames/
        prompts/
        animations/
        output/
        logs/
        manifests/
```

## Shared Data Contracts

To make the scripts work together, each run should use the same file conventions.

### Core files

- `data/runs/<run_id>/manifests/run.json`
  - global metadata for the current job
  - source video path
  - total clip count
  - overall status

- `data/runs/<run_id>/manifests/clips.json`
  - list of all clips in sequence order
  - start and end timestamps
  - clip file paths

- `data/runs/<run_id>/clips/<clip_id>/analysis.json`
  - lighting
  - camera angle
  - camera type
  - action summary
  - optional motion notes

- `data/runs/<run_id>/clips/<clip_id>/frame_prompt.txt`
  - prompt used to create a modified first frame

- `data/runs/<run_id>/clips/<clip_id>/animation_prompt.txt`
  - prompt used for the image-to-video generation step

- `data/runs/<run_id>/clips/<clip_id>/status.json`
  - current state of that clip in the pipeline
  - frame generated or not
  - animation requested or not
  - animation completed or not

## Script List

## 1. `setup_run.py`

Creates the run folder structure and initializes manifest files.

### Inputs

- source video path
- optional run name

### Outputs

- `run.json`
- folder tree for the new run

## 2. `ingest_video.py`

Copies or links the input viral video into the run folder and records metadata such as duration, resolution, and frame rate.

### Inputs

- source video path
- `run_id`

### Outputs

- local input video file inside the run folder
- updated `run.json`

## 3. `detect_scenes.py`

Detects scene changes or clip boundaries in the input video.

This is the script that decides how the source video should be split into clips.

### Inputs

- input video
- detection sensitivity settings

### Outputs

- scene boundary timestamps
- preliminary `clips.json`

## 4. `split_clips.py`

Uses the detected scene boundaries to export each clip as its own video file.

### Inputs

- input video
- scene timestamps from `clips.json`

### Outputs

- per-clip video files
- updated `clips.json` with file paths

## 5. `analyze_clip.py`

Analyzes one clip and produces structured information about:

- lighting
- camera angle
- camera type
- visible action
- optional movement/style notes

This can call a vision-capable model or another analysis service.

### Inputs

- one clip path

### Outputs

- `analysis.json` for that clip

## 6. `analyze_all_clips.py`

Loops over all clips and runs `analyze_clip.py` for each one.

This script exists so clip-level analysis stays isolated while batch execution stays simple.

### Inputs

- `run_id`

### Outputs

- all clip analysis files

## 7. `extract_first_frame.py`

Extracts the first frame from a single clip.

### Inputs

- clip path

### Outputs

- first-frame image for that clip

## 8. `extract_all_first_frames.py`

Runs first-frame extraction for every clip.

### Inputs

- `run_id`

### Outputs

- all extracted first-frame images

## 9. `generate_frame_prompt.py`

Builds the text prompt that will be sent to ChatGPT for frame modification.

The prompt should include:

- a description of the clip
- analysis metadata
- instructions to preserve the scene structure
- instructions to make the frame original in details

### Inputs

- extracted first frame
- `analysis.json`

### Outputs

- `frame_prompt.txt`

## 10. `modify_frame_with_chatgpt.py`

Sends the first frame and prompt to ChatGPT or another image-editing model to create a modified version of the frame.

### Inputs

- original first frame
- `frame_prompt.txt`

### Outputs

- modified frame image
- request metadata

## 11. `modify_all_frames.py`

Runs the frame modification step for all clips.

### Inputs

- `run_id`

### Outputs

- modified first frame for each clip

## 12. `create_animation_prompt.py`

Builds the prompt for the image-to-video model using:

- modified frame
- lighting notes
- camera angle
- camera type
- action description
- clip duration target

### Inputs

- modified frame
- `analysis.json`
- original clip duration

### Outputs

- `animation_prompt.txt`

## 13. `animate_clip.py`

Submits a single modified frame and animation prompt to Grok Imagine or another image-to-video tool.

### Inputs

- modified frame
- `animation_prompt.txt`

### Outputs

- animation job ID
- initial status file

## 14. `animate_all_clips.py`

Submits all clips for animation.

### Inputs

- `run_id`

### Outputs

- animation job IDs for every clip

## 15. `poll_animation_jobs.py`

Checks all outstanding animation jobs until each one is completed or failed.

### Inputs

- `run_id`
- provider job IDs

### Outputs

- downloaded generated clip files
- updated per-clip status

## 16. `merge_clips.py`

Merges the generated clips back together in the original order.

### Inputs

- generated clip files
- `clips.json`

### Outputs

- merged silent video

## 17. `copy_or_rebuild_audio.py`

Handles the audio strategy for the final output.

Possible modes:

- copy original audio track
- remove audio entirely
- rebuild audio later

This script is useful because audio handling may change as the product evolves.

### Inputs

- source video
- merged generated video

### Outputs

- prepared audio track or audio decision metadata

## 18. `assemble_final_video.py`

Combines the merged video with the selected audio strategy and exports the final deliverable.

### Inputs

- merged generated video
- optional audio track

### Outputs

- final output video in `output/`

## 19. `validate_run.py`

Checks that all expected files exist and that the final output is valid.

Validation should include:

- clip count matches the source split
- every clip has analysis
- every clip has a modified frame
- every clip has a generated animation
- final merged video exists

### Inputs

- `run_id`

### Outputs

- validation report

## 20. `cleanup_temp_files.py`

Deletes temporary files that are no longer needed while keeping final artifacts and important manifests.

### Inputs

- `run_id`

### Outputs

- cleaned run folder

## 21. `run_pipeline.py`

This is the top-level orchestration script.

It should run the entire workflow in order:

1. setup run
2. ingest video
3. detect scenes
4. split clips
5. analyze all clips
6. extract all first frames
7. generate and modify all frames
8. create and submit animation jobs
9. poll animation jobs
10. merge clips
11. handle audio
12. assemble final video
13. validate output

### Inputs

- source video path
- output settings
- provider API settings

### Outputs

- full recreated video
- logs and manifests for the run

## How the Scripts Work Together

The intended pipeline is:

```text
setup_run.py
  -> ingest_video.py
  -> detect_scenes.py
  -> split_clips.py
  -> analyze_all_clips.py
  -> extract_all_first_frames.py
  -> modify_all_frames.py
  -> animate_all_clips.py
  -> poll_animation_jobs.py
  -> merge_clips.py
  -> copy_or_rebuild_audio.py
  -> assemble_final_video.py
  -> validate_run.py
```

Batch scripts such as `analyze_all_clips.py`, `extract_all_first_frames.py`, `modify_all_frames.py`, and `animate_all_clips.py` should call the single-item scripts internally or reuse the same shared logic.

## External Integrations We Will Need

- `ffmpeg` for video splitting, frame extraction, and merging
- OpenAI API or ChatGPT image-editing workflow for frame modification
- Grok Imagine or another image-to-video API for clip animation
- optional scene detection library such as `PySceneDetect`

## Recommended Build Order

The scripts should be implemented in this order:

1. `setup_run.py`
2. `ingest_video.py`
3. `detect_scenes.py`
4. `split_clips.py`
5. `extract_first_frame.py`
6. `analyze_clip.py`
7. `generate_frame_prompt.py`
8. `modify_frame_with_chatgpt.py`
9. `create_animation_prompt.py`
10. `animate_clip.py`
11. `poll_animation_jobs.py`
12. `merge_clips.py`
13. `assemble_final_video.py`
14. `validate_run.py`
15. batch and orchestration scripts

## Notes

- Every script should accept command-line arguments so it can be run independently.
- Every script should write logs to the run folder.
- Every script should fail clearly with a useful error message.
- Every script should be rerunnable without corrupting the run state.
- JSON should be used for structured metadata passed between scripts.
