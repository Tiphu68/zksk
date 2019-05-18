from primitives.DLRep import * 
from Subproof import *
from CompositionProofs import *
from SigmaProtocol import *
from BilinearPairings import *
import pdb



class Signature:
    def __init__(self, A, e, s):
        self.A = A
        self.e = e
        self.s = s



class KeyPair:
    def __init__(self, bilinearpair, length):
        """
        length should be an upperbound on the number of messages
        """

        self.generators = []
        self.henerators = []
        g = bilinearpair.G1.generator()
        h = bilinearpair.G2.generator()
        order = bilinearpair.G1.order()
        for i in range(length+2):
            self.generators.append(order.random()*g)
            self.henerators.append(order.random()*h)
            """
            randWord = randomword(30).encode("UTF-8")
            randWord2 = randomword(30).encode("UTF-8")
            self.generators.append(bilinearpair.G1.hash_to_point(randWord))
            self.henerators.append(bilinearpair.G2.hash_to_point(randWord))
            """

        self.sk = SecretKey(order.random(), self)
        self.pk = PublicKey(self.sk.gamma*self.henerators[0], self.generators, self.henerators)
        self.sk.pk = self.pk

class PublicKey:
    def __init__(self, w, generators, henerators):
        self.w = w
        self.generators = generators
        self.henerators = henerators
        self.h0 = self.henerators[0]

    def verify_signature(self, signature, messages):
        generators =self.generators[:len(messages)+1]
        product = generators[0] + create_lhs(generators[1:], [signature.s]+messages)
        return signature.A.pair(self.w+signature.e*self.h0) == product.pair(self.h0)



class SecretKey:
    def __init__(self, value, keypair):
        self.generators = keypair.generators
        self.henerators = keypair.henerators
        self.h0 = self.henerators[0]
        self.group = self.h0.group
        self.gamma = value

    def sign(self, cmessages):
        """
        Signs a committed message Cm ie returns A,e,s such that A = (g0 + s*g1 + Cm) * 1/e+gamma
        >>> G = BilinearGroupPair()
        >>> gens = [2,3,4]*G.G1.generator()
        >>> hens = [2,3,4]*G.G2.generator()
        >>> pk, sk = gen_keys(gens, hens)

        >>> A,e,s2 = s.sign()
        >>> (e + s.gamma)*A == self.verifier.lhs
        True
        """
        pedersen_product = cmessages
        e = self.group.order().random()
        s2 = self.group.order().random()
        prod = self.generators[0]+s2*self.generators[1]+pedersen_product
        A = (self.gamma+e).mod_inverse(self.group.order())*prod
        return Signature(A,e,s2)

def verify_proof(self, NIproof, lhs, generators):
    """
    Prototypes a ZK proof for the Pedersen commitment to messages and uses it to
    verify the non-interactive proof passed as argument.
    """
    secret_names = ["s1"] + ["m"+str(i+1)for i in range (len(generators)-2)]
    proof = DLRepProof(lhs, create_rhs(secret_names, generators[1:]))
    return proof.get_verifier().verify_NI(*NIproof, encoding=enc_GXpt)

def user_commit(messages, generators, to_sign):
    """
    Prepare a pedersen commitment for the correct construction of the sequence to be signed.
    Returns a non-interactive proof as well as a verifier object able to verify the said proof.
    """
    s1 = generators[0].group.order().random()
    cmessages = s1*generators[1]+ to_sign

    #define secret names as s' m1 m2 ...mL
    names = ["s'"] + ["m"+str(i+1) for i in range(len(messages))] 
    secrets = [s1] + messages

    pedersen_proof = DLRepProof(cmessages, create_rhs(names, generators))
    pedersen_prover = pedersen_proof.get_prover(dict(zip(names, secrets)))
    return pedersen_prover.get_NI_proof(encoding=enc_GXpt), pedersen_proof.get_verifier(), s1, cmessages


    
def sign_and_verify(messages, keypair, zkp=0):
    """
    Wrapper method which given a set of generators and messages, performs the whole protocol from the key generation to the signature verification.
    """
    pk, sk = keypair.pk, keypair.sk

    #We work with the exact number of generators we need since now we know the number of messages
    L = len(messages)+2
    generators, henerators = keypair.generators[:L], keypair.henerators[L]

    s1 = Bn(0)
    presigned = create_lhs(generators[2:], messages)

    if zkp:
        """
        If we require proof of correct construction, we should add a blinding factor. 
        """
        pedersen_NI, s1, presigned = user_commit(messages, generators, to_sign)
        if verify_proof(pedersen_NI, presigned, generators):
            print("Pedersen commitment verified.")
    print("Signing...")
    
    signature = sk.sign(presigned)
    print("Done signing..")

    # Updating the signature exponent (unchanged if no shadowing term)
    signature.s = s1+signature.s

    if pk.verify_signature(signature, messages) :
        print ("Signature verified!")
        return True
    return False

class SignatureProof(Proof):
    """
    Proof of knowledge of a (A,e,s) signature over a set of messages.
    """
    def __init__(self, pk, sk):
        """
        Instantiates a Signature Proof which is an enhanced version of AndProof allowing to access additional parameters
        """
        #preprocess all is needed for the signature PK
        self.generators = pk.generators
        self.h0 = pk.h0
        self.w = pk.w



    def get_prover(self, secret_dict, A):
        prov = SignatureProver(None)
        A1,A2 = prov.precommit(self.generators, A)

        self.andproof = build_pi5(A1, A2)

        andprover = self.andproof.get_prover(secret_dict)
        prov.__init__(andprover)
        return prov
    
    def get_verifier(self):
        return SignatureVerifier(self.andproof.get_verifier())


    def build_pi5(self, A1, A2):
        """
        A template for the proof of knowledge of a signature pi5 detailed on page 7 of the following paper : https://eprint.iacr.org/2008/136.pdf
        It uses group pairings, DLRep and And Proofs.
        public info should be : 
            - w (public key), 
            - h0 (base of the public key), 
            - generators (of length len(m)+2)

        """
        gT = self.h0.gtgroup
        L = len(self.generators)-2
        g0, g1, g2 = self.generators[0], self.generators[1], self.generators[2]
        dl1 = DLRepProof(A1, Secret("r1")*g1 + Secret("r2"*g2))
        dl2 = DLRepProof(gT.infinite(), Secret("delta1")*g1 + Secret("delta2")*g2 + Secret("e")*(-A1))

        signature = AndProof(dl1, dl2)


        gen_pairs = [gT.pair(self.generators[k], self.h0) for k in range(L+2)]

        lhs = gT.pair(A2, w)-gen_pairs[0]
        generators = [-gT.pair(A2, self.h0), gT.pair(self.generators[1], w), gen_pairs[1]]
        generators.extend(gen_pairs[1:])

        self.secret_names = ["e", "r1", "delta1", "s"]
        """
        Notice we replace -e*g by e*(-g) so the system recognizes e as reoccuring secret through subproofs
        """
        for k in range(L):
            self.secret_names.append("m"+str(k+1))
        """
        
        gen_pairs is an array of the form epair(gi, h0)
        generators is the list of elements to multiply i.e all pairings
        secret_names are the exponents (ordered) ie -e, r1, delta1, s, m_i as specified in the protocol
        """

        pairings_proof = DLRepProof(lhs, create_rhs(secret_names, generators))

        return AndProof(signature, pairings_proof)
    #The sigature proof is ready to be used, either with an interactive sigma protocol, 
    # a NI proof or even a simulation (just specify dummy secrets for the proof building and then pass an empty dict to the prover)



class SignatureProver(AndProofProver):
    """TODO: fix. does it inherit from AndProofProver or is it a wrapper?
    """
    def __init__(self, andprover):
        if andprover is None:
            return
        self.andp = andprover
        self.secret_values = andprover.secret_values

    def precommit(generators, A):
        """
        Generate LHS A1, A2 for the signature proof
        """
        self.r1 = generators[0].group.order().random()
        self.r2 = generators[0].group.order().random()
        a1 = generators[1]*r1+generators[2]*r2
        a2 = A+generators[2]*r1
        return a1, a2


class SignatureVerifier(AndProofVerifier):
    pass