import re

from collections import OrderedDict

from theano.scalar import ScalarConstant
from theano.tensor import TensorConstant
from theano.tensor.sharedvar import SharedVariable

from blocks.utils import dict_union

class Model(object):
    """Model is a container for bricks that form a single trainable entity.

    Parameters
    ----------
    top_bricks : list of Bricks
        The top-level bricks of the model (those which are not children
        of another brick).
    basic_cost : Theano variable
        The model cost before regularization.
    """

    def __init__(self, top_bricks, basic_cost):
        self.top_bricks = tuple(top_bricks)
        for brick in self.top_bricks:
            assert brick.allocated
        self.basic_cost = basic_cost
        self._get_variables()

    def cost(self):
        return self.basic_cost

    def select(self, path=None):
        selection = Selector(self.top_bricks)
        if path:
            selection = selection.select(path)
        return selection

    def get_params(self):
        return self.select().get_params()

    def _get_variables(self):
        def recursion(current):
            if current.owner:
                for inp in current.owner.inputs:
                    if not inp in self.variables:
                        recursion(inp)
                self.variables.add(inp)

        def is_input(variable):
            return (not variable.owner
                    and not isinstance(variable, SharedVariable)
                    and not isinstance(variable, TensorConstant)
                    and not isinstance(variable, ScalarConstant))

        self.variables = set()
        recursion(self.cost())
        self.input_variables = [v for v in self.variables if is_input(v)]

class Path(object):
    """Encapsulates a path in a hierarchy of bricks.

    Current the only allowed elements of pathes are names of the bricks
    and names of parameters. The latter can only be put in the end of the
    path. It is planned to support regular expressions in some way later.

    Parameters
    ----------
    nodes : list or tuple of path nodes
        The nodes of the part.

    """

    separator = "/"
    param_separator = "."
    separator_re = re.compile("([{}{}])".format(separator, param_separator))

    class BrickName(str):

        def part(self):
            return Path.separator + self

    class ParamName(str):

        def part(self):
            return Path.param_separator + self

    def __init__(self, nodes):
        assert isinstance(nodes, (list, tuple))
        self.nodes = tuple(nodes)

    def __str__(self):
        return "".join([node.part() for node in self.nodes])

    def __add__(self, other):
        return Path(self.nodes + other.nodes)

    def __eq__(self, other):
        return self.nodes == other.nodes

    def __hash__(self):
        return hash(self.nodes)

    @staticmethod
    def parse(string):
        """Constructs a path from its string representation.

        Parameters
        ----------
        string : str
            String representation of the part.

        .. todo::

            More error checking.

        """
        elements = Path.separator_re.split(string)[1:]
        separators = elements[::2]
        parts = elements[1::2]
        assert len(elements) == 2 * len(separators) == 2 * len(parts)

        nodes = []
        for separator, part in zip(separators, parts):
            if separator == Path.separator:
                nodes.append(Path.BrickName(part))
            elif Path.param_separator == Path.param_separator:
                nodes.append(Path.ParamName(part))
            else:
                # This can not if separator_re is a correct regexp
                raise ValueError("Wrong separator {}".format(separator))

        return Path(nodes)


class Selector(object):
    """Selection of elements of a hierarchy of bricks.

    Parameters
    ----------
    bricks : list of Bricks
        The bricks of the selection.

    """

    def __init__(self, bricks):
        self.bricks = bricks

    def select(self, path):
        """Select a subset of current selection matching the path given.

        Parameters
        ----------
        path : :class:`Path` or str
            The path for the desired selection. If a string is given
            it is parsed into a path.

        .. warning::

            Current implementation is very inefficient (theoretical
            complexity is :math:`O(n^3)`, where :math:`n` is the number
            of bricks in the hierarchy). It can be sped up easily.

        Returns
        -------

        Depending on the path given, one of the following:

        * A :class:`Selector` with desired bricks.
        * A list of shared Theano variables.

        """
        if isinstance(path, basestring):
            path = Path.parse(path)

        current_bricks = [None]
        for node in path.nodes:
            next_bricks = []
            if isinstance(node, Path.ParamName):
                return Selector(current_bricks).get_params(node).values()
            if isinstance(node, Path.BrickName):
                for brick in current_bricks:
                    children = brick.children if brick else self.bricks
                    matching_bricks = [child for child in children
                                       if child.name == node]
                    for match in matching_bricks:
                        if not match in next_bricks:
                            next_bricks.append(match)
            current_bricks = next_bricks
        return Selector(current_bricks)

    def get_params(self, param_name=None):
        """Returns parameters the selected bricks and their ancestors.

        Parameters
        ----------
        param_name : :class:`Path.ParamName`
            If given, only parameters with the name `param_name` are returned.

        Returns
        -------
        A dictionary of (`path`, `param`) pairs, where `path` the string
        representation of the part to the parameter, `param` is the parameter.

        """
        def recursion(brick):
            # TODO path logic should be separate
            result = [(Path([Path.BrickName(brick.name),
                             Path.ParamName(param.name)]),
                             param)
                      for param in brick.params
                      if not param_name or param.name == param_name]
            result = OrderedDict(result)
            for child in brick.children:
                for path, param in recursion(child).items():
                    new_path = Path([Path.BrickName(brick.name)]) + path
                    result[new_path] = param
            return result
        result = dict_union(*[recursion(brick)
                             for brick in self.bricks])
        return OrderedDict((str(key), value) for key, value in result.items())

