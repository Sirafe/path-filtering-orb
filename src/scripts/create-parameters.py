import json
import os
import re
import subprocess
from functools import partial

def checkout(revision):
  """
  Helper function for checking out a branch

  :param revision: The revision to checkout
  :type revision: str
  """
  subprocess.run(
    ['git', 'checkout', revision],
    check=True
  )

def merge_base(base, head):
  return subprocess.run(
    ['git', 'merge-base', base, head],
    check=True,
    capture_output=True
  ).stdout.decode('utf-8').strip()

def parent_commit():
  return subprocess.run(
    ['git', 'rev-parse', 'HEAD~1'],
    check=True,
    capture_output=True
  ).stdout.decode('utf-8').strip()

def is_valid_regex(string):
  try:
    re.compile(string)
    return True
  except re.error:
    return False

def compare_tags(ref_tag, *tags):
  if is_valid_regex(ref_tag):
    if all(re.match(ref_tag.strip("/"), tag) for tag in tags):
      return True
    return False
  else:
    raise Exception('Invalid regex provided in reference tag "{}"'.format(ref_tag))

def get_previous_tagged_commit(ref_tag):
  last_tag_hash = subprocess.run(
    ['git', 'rev-list', '--tags', '--skip=1', '--max-count=1'],
    check=True,
    capture_output=True
  ).stdout.decode('utf-8').strip()

  tag_label = subprocess.run(
    ['git', 'describe', '--abbrev=0', '--tags', last_tag_hash],
    check=True,
    capture_output=True
  ).stdout.decode('utf-8').strip()

  is_match = compare_tags(ref_tag, tag_label)

  if not is_match:
    return None

  return last_tag_hash, tag_label


def changed_files(base, head):
  return subprocess.run(
    ['git', '-c', 'core.quotepath=false', 'diff', '--name-only', base, head],
    check=True,
    capture_output=True
  ).stdout.decode('utf-8').splitlines()

filtered_config_list_file = "/tmp/filtered-config-list"

def write_filtered_config_list(config_files):
  with open(filtered_config_list_file, 'w') as fp:
    fp.writelines(config_files)

def write_mappings(mappings, output_path):
  with open(output_path, 'w') as fp:
    fp.write(json.dumps(mappings))

def write_parameters_from_mappings(mappings, changes, output_path, config_path):
  if not mappings:
    raise Exception("Mapping cannot be empty!")

  if not output_path:
    raise Exception("Output-path parameter is not found")

  element_count = len(mappings[0])

  # currently the supported format for each of the mapping parameter is either:
  # path-regex pipeline-parameter pipeline-parameter-value
  # OR
  # path-regex pipeline-parameter pipeline-parameter-value config-file
  if not (element_count == 3 or element_count == 4):
    raise Exception("Invalid mapping length of {}".format(element_count))

  filtered_mapping = []
  filtered_files = set()

  for m in mappings:
    if len(m) != element_count:
      raise Exception("Expected {} fields but found {}".format(element_count, len(m)))

    if element_count == 3:
      path, param, param_value = m
      config_file = None
    else:
      path, param, param_value, config_file = m

    try:
      decoded_param_value = json.loads(param_value)
    except ValueError:
      raise Exception("Cannot parse pipeline value {} from mapping".format(param_value))

    # type check pipeline parameters - should be one of integer, string, or boolean
    if not isinstance(decoded_param_value, (int, str, bool)):
      raise Exception("""
        Pipeline parameters can only be integer, string or boolean type.
        Found {} of type {}
        """.format(decoded_param_value, type(decoded_param_value)))

    regex = re.compile(r'^' + path + r'$')
    for change in changes:
      if regex.match(change):
        filtered_mapping.append([param, decoded_param_value])
        if config_file:
          filtered_files.add(config_file + "\n")
        break

  if not filtered_mapping:
    print("No change detected in the paths defined in the mapping parameter")

  write_mappings(dict(filtered_mapping), output_path)

  if not filtered_files:
    filtered_files.add(config_path)

  write_filtered_config_list(filtered_files)

def is_mapping_line(line: str) -> bool:
  is_empty_line = (line.strip() == "")
  is_comment_line = (line.strip().startswith("#"))
  return not (is_comment_line or is_empty_line)

def create_parameters(output_path, config_path, head, base, ref_tag, head_tag, mapping):
  if head_tag and ref_tag and compare_tags(ref_tag, head_tag):
    print(
      'Head tag detected "{}". This is a tagged commit, a reference tag was supplied, and the current tag matches the provided reference tag. '
      'Finding previously tagged commit matching the provided reference tag "{}"'.format(head_tag, ref_tag)
    )
    result = get_previous_tagged_commit(ref_tag) #Get the previous commit, and tag label with a matching tag, or 'None' if the previous tag doesn't match the reference
    if result is not None:
      base, base_tag = result
      print('Base has been set to "{}" with the tag "{}"'.format(base, base_tag))
    else:
      print('The previous tag did not match the provided reference tag. We will continue as normal. Comparing as usual.')

  checkout(base)  # Checkout base revision to make sure it is available for comparison
  checkout(head)  # return to head commit
  base = merge_base(base, head)

  if head == base:
    try:
      # If building on the same branch as BASE_REVISION, we will get the
      # current commit as merge base. In that case try to go back to the
      # first parent, i.e. the last state of this branch before the
      # merge, and use that as the base.
      base = parent_commit()
    except:
      # This can fail if this is the first commit of the repo, so that
      # HEAD~1 actually doesn't resolve. In this case we can compare
      # against this magic SHA below, which is the empty tree. The diff
      # to that is just the first commit as patch.
      base = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

  print('Comparing {}...{}'.format(base, head))
  changes = changed_files(base, head)

  if os.path.exists(mapping):
    with open(mapping) as f:
      mappings = [
        m.split() for m in f.read().splitlines() if is_mapping_line(m)
      ]
  else:
    mappings = [
      m.split() for m in
      mapping.splitlines() if is_mapping_line(m)
    ]

  write_parameters_from_mappings(mappings, changes, output_path, config_path)


if __name__ == "__main__":
  create_parameters(
    os.environ.get('OUTPUT_PATH'),
    os.environ.get('CONFIG_PATH'),
    os.environ.get('CIRCLE_SHA1'),
    os.environ.get('BASE_REVISION'),
    os.environ.get('TAG_REFERENCE'),
    os.environ.get('CIRCLE_TAG'),
    os.environ.get('MAPPING')
  )
