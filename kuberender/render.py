import collections
import os
import sys
from functools import partial
from os.path import expanduser
from subprocess import PIPE, Popen

import dpath
import jinja2
import yaml
from libvcs.shortcuts import create_repo_from_pip_url

RenderedTemplate = collections.namedtuple('RenderedTemplate', ['slug', 'content'])


def merge_dicts(dicts):
    merged = {}
    for d in dicts:
        dpath.util.merge(merged, d)
    return merged


def should_render_template(template_path):
    filename = template_path.split('/')[-1]
    return not (filename.startswith('.') or filename.startswith('_'))


def render_templates(template_dir, working_dir, **context):
    loader = jinja2.FileSystemLoader([working_dir, template_dir])
    env = jinja2.Environment(loader=loader)
    env.filters['dump'] = lambda o: yaml.dump(o, default_flow_style=False)

    def render(filename):
        template = env.get_template(filename)

        rendered = template.render(yaml=yaml, **context)
        return RenderedTemplate(filename, rendered)
    return map(render, filter(should_render_template, os.listdir(template_dir)))


def load_yaml_file(path):
    with open(path) as f:
        return yaml.load(f.read())


def parse_overriden_vars(overriden_vars):
    def parse_statement(override_statement):
        key, value = override_statement.split('=')
        obj = {}
        dpath.util.new(obj, key, value, separator='.')
        return obj

    return list(map(parse_statement, overriden_vars))


def update_templates(template_url, dump_dir):
    repo = create_repo_from_pip_url(pip_url=template_url, repo_dir=dump_dir)
    repo.update_repo()


def render(verbose, template_dir, should_apply, context_files, overriden_vars, template_url, working_dir):
    change_working_dir = partial(os.path.join, working_dir)
    context_data = map(load_yaml_file, map(change_working_dir, context_files))

    overriden_vars = parse_overriden_vars(overriden_vars)
    context = merge_dicts(context_data + overriden_vars)

    if template_url is not None:
        template_dir = os.path.join(expanduser("~"), '.kube-render/templates')
        update_templates(template_url, template_dir)
    else:
        template_dir = change_working_dir(template_dir)

    rendered_templates = render_templates(template_dir, working_dir, **context)

    if verbose:
        sys.stdout.write('### Computed context:\n')
        sys.stdout.write(yaml.safe_dump(context, default_flow_style=False, indent=2))
        for t in rendered_templates:
            sys.stdout.write('\n### Rendered {}\n'.format(t.slug))
            sys.stdout.write(t.content)
            sys.stdout.write('\n')

    return rendered_templates


def create_kubectl_apply_pipe():
    return Popen(['kubectl', 'apply', '-f', '-'], stdin=PIPE)


def call_kubectl_apply(template):
    if not (yaml.load(template.content) or {}).get('kind'):
        return
    pipe = create_kubectl_apply_pipe()
    pipe.communicate(template.content)
    return pipe.wait()


def apply_templates(rendered_templates):
    return map(call_kubectl_apply, rendered_templates)


def run(verbose, template_dir, should_apply, context_files, overriden_vars, template_url, working_dir):
    return_code = 0
    rendered_templates = render(verbose, template_dir, should_apply, context_files, overriden_vars, template_url, working_dir)
    if should_apply:
        return_code = all(apply_templates(rendered_templates))
    return return_code
